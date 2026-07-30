"""Public, secret-free URL ingestion wire models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from akc_url_fetcher.models import UrlFetchTask


class UrlFetchTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    task_id: uuid.UUID
    document_id: uuid.UUID
    project_id: uuid.UUID
    status: Literal[
        "queued",
        "running",
        "retry",
        "completed",
        "failed",
        "dead_letter",
        "cancelled",
    ]
    canonical_url: str = Field(max_length=2048)
    query_hmac: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1, le=10)
    error_code: str | None = None
    content_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source_file_id: uuid.UUID | None = None
    status_url: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None


def url_fetch_task_response(task: UrlFetchTask) -> UrlFetchTaskResponse:
    return UrlFetchTaskResponse(
        task_id=task.id,
        document_id=task.document_id,
        project_id=task.project_id,
        status=cast(Any, task.status),
        canonical_url=task.canonical_url,
        query_hmac=task.query_hmac,
        attempt_count=task.attempt_count,
        max_attempts=task.max_attempts,
        error_code=task.last_error_code,
        content_type=task.content_type,
        size_bytes=task.size_bytes,
        source_sha256=task.source_sha256,
        source_file_id=task.source_file_id,
        status_url=f"/v1/url-fetch-tasks/{task.id}",
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
        cancelled_at=task.cancelled_at,
    )
