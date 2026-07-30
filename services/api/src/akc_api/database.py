"""Async SQLAlchemy setup supporting PostgreSQL and SQLite development."""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Request
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from akc_api.settings import Settings


class Base(DeclarativeBase):
    """Declarative metadata root."""


_DEFER_COMMIT_KEY = "akc_idempotency_defer_commit"
_DEFER_COMMIT_REQUESTED_KEY = "akc_idempotency_commit_requested"


class ApplicationAsyncSession(AsyncSession):
    """Request session whose final commit can be owned by an API wrapper.

    Mutation endpoints predate the global idempotency contract and commit
    explicitly.  During an idempotent call those commits become flushes so the
    mutation and its replay record can be finalized in one database
    transaction.
    """

    async def commit(self) -> None:
        if self.info.get(_DEFER_COMMIT_KEY):
            self.info[_DEFER_COMMIT_REQUESTED_KEY] = True
            await self.flush()
            return
        await super().commit()


def defer_session_commit(session: AsyncSession) -> None:
    session.info[_DEFER_COMMIT_KEY] = True
    session.info[_DEFER_COMMIT_REQUESTED_KEY] = False


def deferred_session_commit_requested(session: AsyncSession) -> bool:
    return bool(session.info.get(_DEFER_COMMIT_REQUESTED_KEY))


async def commit_deferred_session(session: AsyncSession) -> None:
    session.info.pop(_DEFER_COMMIT_KEY, None)
    session.info.pop(_DEFER_COMMIT_REQUESTED_KEY, None)
    await AsyncSession.commit(session)


def clear_deferred_session_commit(session: AsyncSession) -> None:
    session.info.pop(_DEFER_COMMIT_KEY, None)
    session.info.pop(_DEFER_COMMIT_REQUESTED_KEY, None)


class Database:
    """Owns one async engine and transaction-scoped sessions."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if settings.database_url.startswith("sqlite"):
            database_file = settings.database_url.rsplit("///", 1)[-1]
            if database_file not in {":memory:", ""}:
                Path(database_file).parent.mkdir(parents=True, exist_ok=True)
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            echo=False,
        )
        if settings.database_url.startswith("sqlite"):

            @event.listens_for(self.engine.sync_engine, "connect")
            def _sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
                cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        self.sessions = async_sessionmaker(
            bind=self.engine,
            class_=ApplicationAsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    async def create_schema(self) -> None:
        from akc_url_fetcher import models as _url_models  # noqa: F401

        from akc_api import models as _models  # noqa: F401
        from akc_api import project_access_models as _project_access_models  # noqa: F401
        from akc_api import team_models as _team_models  # noqa: F401

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()


def _jwt_context_hint(token: str) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Read unverified IDs only to narrow RLS before authentication.

    Authentication still verifies the signature and membership. An attacker
    can therefore only make their own query see fewer/different tenant rows;
    they cannot bypass the later credential check.
    """

    try:
        payload_segment = token.split(".", 2)[1]
        padding = "=" * (-len(payload_segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_segment + padding))
        tenant_id = uuid.UUID(str(payload["tid"]))
        user_id = uuid.UUID(str(payload["sub"]))
    except (
        IndexError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        binascii.Error,
    ):
        return None, None
    return tenant_id, user_id


def _request_context_hint(
    request: Request, settings: Settings
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    authorization = request.headers.get("Authorization", "")
    token = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
    if token.startswith("akc_live_"):
        # New API keys embed an opaque tenant UUID hint. The complete token is
        # still verified by its high-entropy SHA-256 digest.
        try:
            parts = token.removeprefix("akc_live_").split("_")
            # URL-safe random segments may themselves contain underscores, so
            # fixed split positions are not trustworthy. The tenant hint is
            # the only canonical 32-character UUID hex segment in both the
            # current and legacy key formats.
            tenant_id = next(
                uuid.UUID(hex=part)
                for part in parts
                if len(part) == 32
            )
            return tenant_id, None
        except (StopIteration, ValueError):
            return None, None
    if not token:
        token = request.cookies.get(settings.session_cookie_name, "")
    return _jwt_context_hint(token) if token else (None, None)


async def set_rls_context(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> None:
    """Set transaction-local PostgreSQL RLS context.

    SQLite is the deterministic development adapter and has no SET LOCAL.
    """

    if session.bind is None or session.bind.dialect.name != "postgresql":
        return
    if tenant_id is not None:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :value, true)"),
            {"value": str(tenant_id)},
        )
    if user_id is not None:
        await session.execute(
            text("SELECT set_config('app.user_id', :value, true)"),
            {"value": str(user_id)},
        )


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide one request session with the narrowest available RLS hint."""

    database: Database = request.app.state.database
    async with database.sessions() as session:
        session.info["akc_request"] = request
        tenant_id, user_id = _request_context_hint(request, database.settings)
        await set_rls_context(session, tenant_id=tenant_id, user_id=user_id)
        yield session
