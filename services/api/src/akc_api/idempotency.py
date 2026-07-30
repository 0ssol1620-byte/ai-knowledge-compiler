"""Transaction-safe idempotency for tenant-scoped HTTP mutations."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import threading
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Annotated, Any, cast

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute, serialize_response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.database import (
    clear_deferred_session_commit,
    commit_deferred_session,
    defer_session_commit,
    deferred_session_commit_requested,
    set_rls_context,
)
from akc_api.models import IdempotencyRecord, utcnow

_LOCKS_GUARD = threading.Lock()
_SQLITE_LOCKS: dict[tuple[str, str], tuple[asyncio.Lock, int]] = {}
_SCOPE_LIMIT = 240


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _validate_key(raw_key: str) -> str:
    if (
        not raw_key
        or len(raw_key) > 200
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in raw_key)
    ):
        raise HTTPException(
            status_code=400,
            detail={"code": "IDEMPOTENCY_KEY_INVALID"},
        )
    return raw_key


def _route_scope(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path", request.url.path)
    scope = f"{request.method.upper()}:{template}"
    if len(scope) > _SCOPE_LIMIT:
        raise HTTPException(
            status_code=500,
            detail={"code": "IDEMPOTENCY_SCOPE_INVALID"},
        )
    return scope


async def canonical_request_hash(request: Request) -> str:
    """Hash the concrete target, sorted query, and canonical request content."""

    raw_body = await request.body()
    content_type = request.headers.get("content-type", "").split(";", 1)[0].casefold()
    body: Mapping[str, Any]
    if content_type == "application/json" and raw_body:
        try:
            body = {"json": json.loads(raw_body)}
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {"sha256": hashlib.sha256(raw_body).hexdigest()}
    else:
        body = {
            "content_type": content_type,
            "sha256": hashlib.sha256(raw_body).hexdigest(),
        }
    canonical = {
        "method": request.method.upper(),
        "route": _route_scope(request),
        "path": request.url.path,
        "query": sorted(request.query_params.multi_items()),
        "body": body,
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _advisory_key(tenant_id: uuid.UUID, scope: str, key: str) -> int:
    digest = hashlib.sha256(f"{tenant_id}:{scope}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


@asynccontextmanager
async def _serialized_request(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    scope: str,
    key: str,
) -> Any:
    bind = session.bind
    if bind is not None and bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": _advisory_key(tenant_id, scope, key)},
        )
        yield
        return

    bind_url = getattr(bind, "url", None)
    if bind_url is None:
        bind_url = getattr(getattr(bind, "engine", None), "url", None)
    database_identity = str(bind_url) if bind_url is not None else str(id(bind))
    lock_key = (database_identity, f"{tenant_id}:{scope}:{key}")
    with _LOCKS_GUARD:
        existing = _SQLITE_LOCKS.get(lock_key)
        lock = existing[0] if existing is not None else asyncio.Lock()
        _SQLITE_LOCKS[lock_key] = (lock, (existing[1] if existing else 0) + 1)
    try:
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
    finally:
        with _LOCKS_GUARD:
            current = _SQLITE_LOCKS.get(lock_key)
            if current is not None:
                users = current[1] - 1
                if users == 0:
                    _SQLITE_LOCKS.pop(lock_key, None)
                else:
                    _SQLITE_LOCKS[lock_key] = (current[0], users)


def _cipher(request: Request) -> Fernet:
    cached = getattr(request.app.state, "idempotency_response_cipher", None)
    if isinstance(cached, Fernet):
        return cached
    key = request.app.state.settings.effective_idempotency_response_encryption_key
    cipher = Fernet(key.encode("ascii"))
    request.app.state.idempotency_response_cipher = cipher
    return cipher


def _encrypt_body(request: Request, body: Any) -> bytes:
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return _cipher(request).encrypt(encoded)


def _decrypt_body(request: Request, record: IdempotencyRecord) -> Any:
    if record.response_body_ciphertext is not None:
        try:
            cleartext = _cipher(request).decrypt(record.response_body_ciphertext)
            return json.loads(cleartext)
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "IDEMPOTENCY_RESPONSE_UNAVAILABLE"},
            ) from exc
    return record.response_body


async def _serialize_response(request: Request, result: Any) -> tuple[int, Any]:
    if isinstance(result, Response):
        status = result.status_code
        if status == 204 or not result.body:
            return status, None
        try:
            return status, json.loads(bytes(result.body))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("idempotent mutation returned a non-JSON response") from exc

    route = cast(APIRoute, request.scope["route"])
    body = await serialize_response(
        field=route.response_field,
        response_content=result,
        include=route.response_model_include,
        exclude=route.response_model_exclude,
        by_alias=route.response_model_by_alias,
        exclude_unset=route.response_model_exclude_unset,
        exclude_defaults=route.response_model_exclude_defaults,
        exclude_none=route.response_model_exclude_none,
        is_coroutine=True,
    )
    return route.status_code or 200, body


def _replay_response(status_code: int, body: Any) -> Response:
    if status_code == 204:
        return Response(status_code=204)
    return JSONResponse(status_code=status_code, content=body)


def _http_exception_response(request: Request, exc: HTTPException) -> JSONResponse:
    raw_detail = cast(object, exc.detail)
    if isinstance(raw_detail, dict):
        detail = {str(key): value for key, value in raw_detail.items()}
    else:
        detail = {"message": str(raw_detail)}
    code = str(detail.pop("code", "HTTP_ERROR"))
    request_id = getattr(
        request.state,
        "request_id",
        request.headers.get("X-Request-ID", f"req_{uuid.uuid4()}"),
    )
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "error": {
                "code": code,
                "message": str(detail.pop("message", code)),
                "request_id": request_id,
                "retryable": exc.status_code >= 500,
                "details": detail,
            }
        },
    )


def _new_record(
    *,
    tenant_id: uuid.UUID,
    scope: str,
    key: str,
    request_hash: str,
    expires_at: datetime,
) -> IdempotencyRecord:
    return IdempotencyRecord(
        tenant_id=tenant_id,
        endpoint=scope,
        idempotency_key=key,
        request_hash=request_hash,
        response_status=None,
        response_body=None,
        response_body_ciphertext=None,
        state="started",
        expires_at=expires_at,
    )


def _complete_record(
    request: Request,
    record: IdempotencyRecord,
    *,
    status_code: int,
    response_body: Any,
) -> None:
    record.response_status = status_code
    record.response_body = None
    record.response_body_ciphertext = _encrypt_body(request, response_body)
    record.state = "completed"


def _context(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> tuple[Request, AsyncSession, uuid.UUID]:
    session = next(
        (value for value in (*kwargs.values(), *args) if isinstance(value, AsyncSession)),
        None,
    )
    if session is None:
        raise RuntimeError("idempotent mutation requires an AsyncSession")
    request = next(
        (value for value in (*kwargs.values(), *args) if isinstance(value, Request)),
        session.info.get("akc_request"),
    )
    if not isinstance(request, Request):
        raise RuntimeError("idempotent mutation requires a Request")
    principal = kwargs.get("principal")
    tenant_id = getattr(principal, "tenant_id", None)
    if not isinstance(tenant_id, uuid.UUID):
        raise RuntimeError("idempotent mutation requires a tenant principal")
    return request, session, tenant_id


def idempotent_mutation[**P, R](
    function: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """Replay successful mutations under the tenant-scoped request key."""

    signature = inspect.signature(function)
    declares_header = "idempotency_key" in signature.parameters

    @wraps(function)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> Any:
        request, session, tenant_id = _context(args, kwargs)
        if not declares_header:
            kwargs.pop("idempotency_key", None)
        header = request.headers.get("Idempotency-Key")
        if header is None:
            return await function(*args, **kwargs)

        key = _validate_key(header)
        scope = _route_scope(request)
        request_hash = await canonical_request_hash(request)
        async with _serialized_request(
            session,
            tenant_id=tenant_id,
            scope=scope,
            key=key,
        ):
            existing = await session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.tenant_id == tenant_id,
                    IdempotencyRecord.endpoint == scope,
                    IdempotencyRecord.idempotency_key == key,
                )
            )
            now = utcnow()
            if existing is not None and _aware(existing.expires_at) <= now:
                await session.delete(existing)
                await session.flush()
                existing = None
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail={"code": "IDEMPOTENCY_CONFLICT"},
                    )
                if existing.state != "completed" or existing.response_status is None:
                    raise HTTPException(
                        status_code=409,
                        detail={"code": "IDEMPOTENCY_INCOMPLETE"},
                    )
                return _replay_response(
                    existing.response_status,
                    _decrypt_body(request, existing),
                )

            expires_at = now + timedelta(days=request.app.state.settings.idempotency_retention_days)
            record = _new_record(
                tenant_id=tenant_id,
                scope=scope,
                key=key,
                request_hash=request_hash,
                expires_at=expires_at,
            )
            session.add(record)
            savepoint = None
            try:
                await session.flush()
                savepoint = await session.begin_nested()
                defer_session_commit(session)
                result = await function(*args, **kwargs)
                status_code, response_body = await _serialize_response(
                    request,
                    result,
                )
                if savepoint.is_active:
                    await savepoint.commit()
                _complete_record(
                    request,
                    record,
                    status_code=status_code,
                    response_body=response_body,
                )
                await session.flush()
                await commit_deferred_session(session)
            except HTTPException as exc:
                commit_requested = deferred_session_commit_requested(session)
                clear_deferred_session_commit(session)
                if savepoint is not None and savepoint.is_active:
                    if commit_requested:
                        await savepoint.commit()
                    else:
                        await savepoint.rollback()
                error_response = _http_exception_response(request, exc)
                if exc.status_code >= 500:
                    if commit_requested and record in session.sync_session:
                        await session.delete(record)
                        await session.flush()
                        await commit_deferred_session(session)
                    else:
                        await session.rollback()
                    raise
                if record not in session.sync_session:
                    await session.rollback()
                    await set_rls_context(session, tenant_id=tenant_id)
                    if session.bind is not None and session.bind.dialect.name == "postgresql":
                        await session.execute(
                            text("SELECT pg_advisory_xact_lock(:lock_key)"),
                            {
                                "lock_key": _advisory_key(
                                    tenant_id,
                                    scope,
                                    key,
                                )
                            },
                        )
                    winner = await session.scalar(
                        select(IdempotencyRecord).where(
                            IdempotencyRecord.tenant_id == tenant_id,
                            IdempotencyRecord.endpoint == scope,
                            IdempotencyRecord.idempotency_key == key,
                        )
                    )
                    if winner is not None:
                        await session.rollback()
                        return error_response
                    record = _new_record(
                        tenant_id=tenant_id,
                        scope=scope,
                        key=key,
                        request_hash=request_hash,
                        expires_at=expires_at,
                    )
                    session.add(record)
                    await session.flush()
                error_body = json.loads(bytes(error_response.body))
                _complete_record(
                    request,
                    record,
                    status_code=exc.status_code,
                    response_body=error_body,
                )
                await session.flush()
                await commit_deferred_session(session)
                return error_response
            except BaseException:
                clear_deferred_session_commit(session)
                if savepoint is not None and savepoint.is_active:
                    await savepoint.rollback()
                await session.rollback()
                raise
            return result

    if not declares_header:
        parameters = [
            *signature.parameters.values(),
            inspect.Parameter(
                "idempotency_key",
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=None,
                annotation=Annotated[
                    str | None,
                    Header(alias="Idempotency-Key"),
                ],
            ),
        ]
        wrapped.__signature__ = signature.replace(  # type: ignore[attr-defined]
            parameters=parameters
        )
    wrapped.__akc_idempotent__ = True  # type: ignore[attr-defined]
    return cast(Callable[P, Awaitable[R]], wrapped)
