"""Anonymous trial ingest boundaries — ADR-006.

These are the properties that make an unauthenticated write surface safe to
expose. Each one is a decision recorded in the ADR, so a change that breaks one
should fail here rather than be discovered in production.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from akc_api.models import Base, Tenant, User
from akc_api.settings import Settings
from akc_api.trial_api import TRIAL_TENANT_ID, TRIAL_USER_ID
from fastapi.testclient import TestClient

PDF = {
    "filename": "filing.pdf",
    "size": 200_000,
    "content_type": "application/pdf",
    "sha256": "a" * 64,
}


def _seed(database: Path) -> None:
    """Create the schema and the rows migration 0023 seeds."""
    engine = sa.create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            sa.insert(Tenant.__table__).values(
                id=TRIAL_TENANT_ID,
                slug="system-trial",
                name="System trial",
                plan_code="trial",
                region="ap-northeast",
                data_retention_days=0,
                private_mode=True,
                external_transfer_allowed=False,
                training_opt_in=False,
                preview_pii_masking=True,
            )
        )
        conn.execute(
            sa.insert(User.__table__).values(
                id=TRIAL_USER_ID,
                email="trial-service@system.invalid",
                password_hash="!",
                display_name="Trial ingest service",
                is_active=False,
            )
        )
    engine.dispose()


def _app_with(database: Path, *, enabled: bool, monkeypatch: pytest.MonkeyPatch):
    """Build an app whose settings actually reflect this test's environment.

    ``get_settings`` is ``lru_cache``d, so without clearing it the first app
    built in the process pins the configuration for every later one — which is
    why these tests passed alone and failed together.
    """
    from akc_api.settings import get_settings

    _seed(database)
    if enabled:
        monkeypatch.setenv("AKC_TRIAL_INGEST_ENABLED", "true")
    else:
        monkeypatch.delenv("AKC_TRIAL_INGEST_ENABLED", raising=False)
    monkeypatch.setenv("AKC_DATABASE_URL", f"sqlite+aiosqlite:///{database.as_posix()}")

    get_settings.cache_clear()
    monkeypatch.setattr(
        get_settings, "cache_clear", get_settings.cache_clear, raising=False
    )

    from akc_api.main import create_app

    app = create_app()
    get_settings.cache_clear()  # leave the process as we found it
    return app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    app = _app_with(tmp_path / "trial.db", enabled=True, monkeypatch=monkeypatch)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def disabled_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    app = _app_with(tmp_path / "trial-off.db", enabled=False, monkeypatch=monkeypatch)
    with TestClient(app) as test_client:
        yield test_client


def _new_session(client: TestClient) -> str:
    created = client.post("/v1/trial/sessions")
    assert created.status_code == 201, created.text
    return str(created.json()["session_id"])


# ── the capability is off by default ────────────────────────────────────────


def test_disabled_capability_answers_404_and_never_422(
    disabled_client: TestClient,
) -> None:
    """A 422 would describe the request schema of an endpoint meant to look absent.

    The well-formed body is the important case: an earlier draft checked the
    flag inside the handler, so FastAPI validated the body first and leaked the
    shape.
    """
    unknown = uuid.uuid4()
    probes = [
        disabled_client.post("/v1/trial/sessions"),
        disabled_client.post(f"/v1/trial/sessions/{unknown}/uploads", json={}),
        disabled_client.post(f"/v1/trial/sessions/{unknown}/uploads", json=PDF),
        disabled_client.get(f"/v1/trial/sessions/{unknown}"),
    ]
    assert [probe.status_code for probe in probes] == [404, 404, 404, 404]


def test_flag_defaults_to_off() -> None:
    assert Settings().trial_ingest_enabled is False


# ── caps ────────────────────────────────────────────────────────────────────


def test_session_reports_the_caps_it_will_enforce(client: TestClient) -> None:
    body = client.post("/v1/trial/sessions").json()
    settings = Settings()
    assert body["max_bytes"] == settings.trial_ingest_max_bytes
    assert body["max_pages"] == settings.trial_ingest_max_pages
    assert body["accepted_content_types"]


def test_oversize_file_is_refused_with_the_limit(client: TestClient) -> None:
    session_id = _new_session(client)
    response = client.post(
        f"/v1/trial/sessions/{session_id}/uploads",
        json={**PDF, "size": 99 * 1024 * 1024},
    )
    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "TRIAL_FILE_TOO_LARGE"
    # The limit is reported, so the caller can act on the refusal.
    assert error["details"]["max_bytes"] == Settings().trial_ingest_max_bytes


def test_unreadable_extension_is_refused(client: TestClient) -> None:
    session_id = _new_session(client)
    response = client.post(
        f"/v1/trial/sessions/{session_id}/uploads",
        json={**PDF, "filename": "clip.mov", "content_type": "video/quicktime"},
    )
    assert response.status_code == 422


def test_one_document_per_session(client: TestClient) -> None:
    """Checked against the project, so a replayed request cannot add a second."""
    session_id = _new_session(client)
    first = client.post(f"/v1/trial/sessions/{session_id}/uploads", json=PDF)
    assert first.status_code == 201
    second = client.post(f"/v1/trial/sessions/{session_id}/uploads", json=PDF)
    assert second.status_code == 409


def test_a_rejected_request_does_not_consume_upload_budget(client: TestClient) -> None:
    """A visitor who mis-picks a file twice must still be able to upload.

    An earlier draft charged the limiter before validating, so two wrong picks
    exhausted the budget and the third — correct — attempt was refused.
    """
    session_id = _new_session(client)
    for _ in range(4):
        rejected = client.post(
            f"/v1/trial/sessions/{session_id}/uploads",
            json={**PDF, "filename": "clip.mov", "content_type": "video/quicktime"},
        )
        assert rejected.status_code == 422
    accepted = client.post(f"/v1/trial/sessions/{session_id}/uploads", json=PDF)
    assert accepted.status_code == 201


# ── session identity is the only credential ─────────────────────────────────


def test_unknown_session_is_indistinguishable_from_expired(client: TestClient) -> None:
    """Otherwise the endpoint reports whether a given id was ever issued."""
    unknown = client.get(f"/v1/trial/sessions/{uuid.uuid4()}")
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "TRIAL_SESSION_NOT_FOUND"


def test_a_session_cannot_read_another_sessions_document(client: TestClient) -> None:
    """Session isolation, which is what stands in for tenant isolation here.

    Both sessions live under the same system tenant, so RLS alone does not
    separate them — the project scoping in the query does.
    """
    first = _new_session(client)
    second = _new_session(client)
    uploaded = client.post(f"/v1/trial/sessions/{first}/uploads", json=PDF)
    assert uploaded.status_code == 201
    first_document = uploaded.json()["document_id"]

    # The second session has no document of its own and must not see the first.
    assert client.get(f"/v1/trial/sessions/{second}").status_code == 404
    assert client.get(f"/v1/trial/sessions/{first}").json()["document_id"] == first_document


def test_presign_never_outlives_the_session(client: TestClient) -> None:
    created = client.post("/v1/trial/sessions").json()
    upload = client.post(
        f"/v1/trial/sessions/{created['session_id']}/uploads", json=PDF
    ).json()
    assert upload["expires_at"] <= created["expires_at"]


# ── the flow stops before the cost surface ──────────────────────────────────


def test_preflight_reports_quarantine_state_not_compiled_output(
    client: TestClient,
) -> None:
    """A freshly presigned document has not been scanned, so nothing is known yet.

    §25.7 — page_count stays null rather than being guessed, and pages_inspected
    is 0 rather than an optimistic number.
    """
    session_id = _new_session(client)
    client.post(f"/v1/trial/sessions/{session_id}/uploads", json=PDF)
    body = client.get(f"/v1/trial/sessions/{session_id}").json()

    assert body["status"] == "UPLOADED"
    assert body["page_count"] is None
    assert body["pages_inspected"] == 0
    assert body["truncated"] is False


def test_no_compile_route_is_exposed_under_the_trial_prefix(
    client: TestClient,
) -> None:
    """The GPU path is the cost surface and must stay behind a principal.

    Read from the OpenAPI document rather than app.routes: that is the surface
    the contract publishes, and it is what a caller can discover.
    """
    paths = {
        path
        for path in client.get("/openapi.json").json()["paths"]
        if path.startswith("/v1/trial")
    }
    assert paths == {
        "/v1/trial/sessions",
        "/v1/trial/sessions/{session_id}/uploads",
        "/v1/trial/sessions/{session_id}/uploads/{upload_id}/content",
        "/v1/trial/sessions/{session_id}/uploads/{upload_id}/complete",
        "/v1/trial/sessions/{session_id}",
    }
    # An exact set rather than a prefix scan, so adding a route to this module
    # fails here and has to be justified. The five above are: open a session,
    # presign, write the bytes, screen them, read the result. Nothing in that
    # list reaches extraction, knowledge, export, or a queue.


# ── configuration cannot be loosened by mistake ─────────────────────────────


def test_trial_cap_cannot_exceed_the_authenticated_cap() -> None:
    """An anonymous caller must not submit a larger object than a paying tenant."""
    with pytest.raises(ValueError, match="trial_ingest_max_bytes"):
        Settings(
            trial_ingest_enabled=True,
            trial_ingest_max_bytes=512 * 1024 * 1024,
            analysis_max_source_bytes=256 * 1024 * 1024,
        )


def test_captcha_threshold_cannot_exceed_the_session_limit() -> None:
    with pytest.raises(ValueError, match="trial_ingest_captcha_after"):
        Settings(
            trial_ingest_enabled=True,
            trial_ingest_captcha_after=9,
            trial_ingest_sessions_per_client=3,
        )


def test_the_caps_do_not_constrain_a_deployment_with_the_flag_off() -> None:
    """The invariant is about anonymous callers, and there are none while off.

    Checking it unconditionally rejected configurations unrelated to trial
    ingest — a deployment tightening analysis_max_source_bytes should not have
    to reason about a disabled feature's defaults.
    """
    settings = Settings(analysis_max_source_bytes=1024 * 1024)
    assert settings.trial_ingest_enabled is False
    assert settings.trial_ingest_max_bytes > settings.analysis_max_source_bytes


def test_captcha_escalates_before_the_hard_limit(client: TestClient) -> None:
    """Repeated session creation is challenged, not silently allowed.

    With no CAPTCHA provider configured — the default outside production — the
    challenge is a refusal, which is fail-closed and is why the threshold sits
    above ordinary use rather than at it. Two sessions must still work.
    """
    settings = Settings()
    assert settings.trial_ingest_captcha_after == 3
    assert settings.trial_ingest_captcha_after < settings.trial_ingest_sessions_per_client

    for _ in range(settings.trial_ingest_captcha_after - 1):
        assert client.post("/v1/trial/sessions").status_code == 201

    escalated = client.post("/v1/trial/sessions")
    assert escalated.status_code == 403
    assert escalated.json()["error"]["code"] == "CAPTCHA_REQUIRED"


# ── expiry is enforced, not just recorded ───────────────────────────────────


def test_expired_session_is_swept_and_becomes_unreadable(
    client: TestClient, tmp_path: Path
) -> None:
    """The one-hour lifetime is what bounds anonymous storage.

    Asserted end to end: create, upload, force the clock past expiry, sweep,
    and confirm the session and its document are both retired and unreadable.
    """
    import asyncio
    from datetime import timedelta

    from akc_api.models import Document, TrialSession
    from akc_api.trial_retention import sweep_expired_trial_sessions
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    session_id = _new_session(client)
    assert client.post(f"/v1/trial/sessions/{session_id}/uploads", json=PDF).status_code == 201
    assert client.get(f"/v1/trial/sessions/{session_id}").status_code == 200

    database = tmp_path / "trial.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database.as_posix()}")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def run() -> tuple[int, int]:
        async with maker() as db:
            trial = await db.get(TrialSession, uuid.UUID(session_id))
            assert trial is not None
            # Age the row rather than sleeping an hour. Both timestamps shift,
            # because the table asserts expires_at > created_at and moving only
            # one of them would violate an invariant the sweep relies on.
            shift = timedelta(hours=2)
            trial.created_at = trial.created_at - shift
            trial.expires_at = trial.expires_at - shift
            await db.commit()
            retired = await sweep_expired_trial_sessions(db)
            marked = await db.scalar(
                sa.select(sa.func.count())
                .select_from(Document)
                .where(Document.deletion_requested_at.is_not(None))
            )
            return retired, int(marked or 0)

    retired, marked_documents = asyncio.run(run())
    asyncio.run(engine.dispose())

    assert retired == 1
    assert marked_documents == 1
    # An expired session must read the same as one that never existed.
    assert client.get(f"/v1/trial/sessions/{session_id}").status_code == 404


def test_sweep_leaves_live_sessions_alone(client: TestClient, tmp_path: Path) -> None:
    import asyncio

    from akc_api.trial_retention import sweep_expired_trial_sessions
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    session_id = _new_session(client)
    database = tmp_path / "trial.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database.as_posix()}")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def run() -> int:
        async with maker() as db:
            return await sweep_expired_trial_sessions(db)

    assert asyncio.run(run()) == 0
    asyncio.run(engine.dispose())
    assert client.get(f"/v1/trial/sessions/{session_id}").status_code in (200, 404)


# --------------------------------------------------------------------------
# Completion: the quarantine path, end to end.
#
# ADR-006 says a trial document runs the same ADR-004 gauntlet as a paid one
# and stops at PREFLIGHTED. Both halves of that are only true if they are
# exercised, so these drive real bytes through the real route rather than
# asserting on the shape of the code.
# --------------------------------------------------------------------------


def _pdf(pages: int = 2) -> bytes:
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _submit(client: TestClient, payload: bytes, *, filename: str = "filing.pdf") -> dict:
    """Session, presign, PUT, complete — the whole visitor journey."""
    import hashlib

    digest = hashlib.sha256(payload).hexdigest()
    session_id = _new_session(client)
    initiated = client.post(
        f"/v1/trial/sessions/{session_id}/uploads",
        json={
            "filename": filename,
            "size": len(payload),
            "content_type": "application/pdf",
            "sha256": digest,
        },
    )
    assert initiated.status_code == 201, initiated.text
    target = initiated.json()

    put = client.put(target["upload_url"], content=payload, headers=target["headers"])
    assert put.status_code == 204, put.text

    completed = client.post(
        f"/v1/trial/sessions/{session_id}/uploads/{target['upload_id']}/complete"
    )
    return {"session_id": session_id, "target": target, "response": completed}


def test_clean_document_reaches_preflighted(client: TestClient) -> None:
    result = _submit(client, _pdf(pages=2))
    response = result["response"]
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "PREFLIGHTED"
    assert body["page_count"] == 2
    assert body["pages_inspected"] == 2
    assert body["truncated"] is False
    assert body["error_code"] is None

    # Polling must agree with what completion returned.
    polled = client.get(f"/v1/trial/sessions/{result['session_id']}")
    assert polled.status_code == 200
    assert polled.json()["status"] == "PREFLIGHTED"


def test_completion_stops_at_preflighted(client: TestClient) -> None:
    """The cost surface stays behind a principal — nothing is enqueued."""
    import sqlalchemy as sa

    result = _submit(client, _pdf(pages=1))
    assert result["response"].json()["status"] == "PREFLIGHTED"

    engine = sa.create_engine(str(client.app.state.settings.database_url).replace(
        "sqlite+aiosqlite", "sqlite"
    ))
    with engine.begin() as conn:
        present = set(sa.inspect(engine).get_table_names())
        for name in ("processing_jobs", "analysis_tasks", "gpu_invocations"):
            if name not in present:
                continue
            # Built through the expression layer rather than interpolated, so
            # the identifier is quoted by SQLAlchemy and this stays a query
            # about table contents rather than a string-formatting exercise.
            count = conn.execute(
                sa.select(sa.func.count()).select_from(sa.table(name))
            ).scalar()
            assert count == 0, f"{name} has {count} rows; trial must not enqueue work"
    engine.dispose()


def test_unsafe_file_is_refused_and_stays_visible(client: TestClient) -> None:
    """§11.2 R3 — the refusal is reported, and the bytes do not survive it."""
    payload = b"MZ\x90\x00" + b"\x00" * 2048  # a PE header behind a .pdf name
    result = _submit(client, payload)
    response = result["response"]
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "SECURITY_REJECTED"
    assert body["error_code"]
    assert body["page_count"] is None

    polled = client.get(f"/v1/trial/sessions/{result['session_id']}")
    assert polled.json()["status"] == "SECURITY_REJECTED"


def test_completion_is_idempotent(client: TestClient) -> None:
    result = _submit(client, _pdf(pages=1))
    assert result["response"].json()["status"] == "PREFLIGHTED"
    again = client.post(
        f"/v1/trial/sessions/{result['session_id']}"
        f"/uploads/{result['target']['upload_id']}/complete"
    )
    assert again.status_code == 200
    assert again.json()["status"] == "PREFLIGHTED"


def test_one_session_cannot_complete_another_sessions_upload(client: TestClient) -> None:
    """Every trial session shares one tenant, so scoping must be by project."""
    victim = _submit(client, _pdf(pages=1))
    attacker_session = _new_session(client)
    stolen = client.post(
        f"/v1/trial/sessions/{attacker_session}"
        f"/uploads/{victim['target']['upload_id']}/complete"
    )
    assert stolen.status_code == 404, stolen.text


def test_document_longer_than_the_cap_is_bounded_not_sliced(client: TestClient) -> None:
    """The page cap bounds the parse, it does not describe its output.

    A slice applied after parsing would still let one anonymous request drive a
    five-hundred-page text extraction. The parser is given the trial's own
    limit instead, so it stops at the page tree — which is also why no page
    count is reported: nothing counted them (§25.7).
    """
    result = _submit(client, _pdf(pages=14))
    body = result["response"].json()
    assert body["status"] == "PREFLIGHTED"
    assert body["truncated"] is True
    assert body["page_count"] is None
    assert body["pages_inspected"] == 0

    # Polling must reconstruct the same thing from the stored row alone.
    polled = client.get(f"/v1/trial/sessions/{result['session_id']}").json()
    assert polled["truncated"] is True
    assert polled["page_count"] is None


def test_document_at_the_cap_is_read_whole(client: TestClient) -> None:
    result = _submit(client, _pdf(pages=10))
    body = result["response"].json()
    assert body["status"] == "PREFLIGHTED"
    assert body["page_count"] == 10
    assert body["pages_inspected"] == 10
    assert body["truncated"] is False
