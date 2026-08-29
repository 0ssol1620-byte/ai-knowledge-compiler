"""Access-Path Conformance harness (청사진 §1.1.E, 위임 기준 §25.6).

11개 접근 경로에서 테넌트 A 주체가 테넌트 B 자원에 접근할 때 동일한 권한
판정(403/404, 내용 누출 0, guessed-UUID와의 비-equivalence)을 ASGI
TestClient 수준에서 실측한다. 서버 실구동 없음, 새 마이그레이션 없음.

감사 이벤트 발행 여부는 매 경로마다 실측해 모듈 전역에 남기고, 마지막 집계
테스트가 11개 경로 모두의 기록을 강제한다.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from akc_api.main import create_app
from akc_api.models import (
    AuditEvent,
    Collection,
    CollectionFile,
    CollectionSourceRoot,
    Document,
    DocumentVersion,
    Export,
    KnowledgeNote,
    PackageManifest,
    Project,
    SourceFile,
    UploadSession,
    User,
    VerificationRecord,
    utcnow,
)
from akc_api.settings import Settings
from sqlalchemy import select

_TEST_SUPPORT_KEY = "access-path-conformance-key"
_PASSWORD = "correct horse battery staple"  # noqa: S105 - test fixture
_METADATA_KEY_ID = "apath-test-key-v1"


# ---------------------------------------------------------------------------
# 경로 매트릭스 (docs/security/access-path-conformance.md §1 과 1:1 대응)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AccessPath:
    """단일 접근 경로의 측정 정의."""

    path_id: str
    surface: str
    blueprint_category: str
    template: str
    # 자원 식별자가 있는 경로는 시드된 B 자원 id로 치환된다.
    # None이면 테넌트 스코프 목록(식별자 없음) 경로다.
    resource_key: str | None = None
    method: str = "GET"


PATHS: tuple[AccessPath, ...] = (
    AccessPath(
        "knowledge_document_get",
        "knowledge_api 개별 문서 조회",
        "GET by ID / guessed UUID",
        "/v1/documents/{resource_id}",
        "document",
    ),
    AccessPath(
        "knowledge_provenance_evidence",
        "문서 provenance/evidence 조회",
        "Evidence lookup",
        "/v1/documents/{resource_id}/provenance",
        "document",
    ),
    AccessPath(
        "knowledge_project_notes_graph",
        "프로젝트 지식 노트 그래프 열람",
        "Graph traversal",
        "/v1/projects/{resource_id}/knowledge",
        "project",
    ),
    AccessPath(
        "collection_integrity_view",
        "컬렉션 integrity 뷰",
        "API",
        "/v1/collections/{resource_id}/integrity",
        "collection",
    ),
    AccessPath(
        "collection_scene_projection",
        "컬렉션 scene 식별자 프로젝션",
        "API",
        "/v1/collections/{resource_id}/scene",
        "collection",
    ),
    AccessPath(
        "collection_events_ledger",
        "컬렉션 이벤트 장부",
        "API",
        "/v1/collections/{resource_id}/events",
        "collection",
    ),
    AccessPath(
        "export_metadata_get",
        "export 메타데이터 조회",
        "Export / API",
        "/v1/exports/{resource_id}",
        "export",
    ),
    AccessPath(
        "export_download_content",
        "export 바이너리 다운로드",
        "Export",
        "/v1/exports/{resource_id}/download",
        "export",
    ),
    AccessPath(
        "team_member_roster",
        "팀 멤버 명단(테넌트 스코프 목록)",
        "API",
        "/v1/team/members",
        None,
    ),
    AccessPath(
        "proof_receipt",
        "소스 proof 영수증",
        "Evidence lookup",
        "/v1/proofs/{resource_id}",
        "verification",
    ),
    AccessPath(
        "trust_receipt_package",
        "패키지 trust receipt",
        "Evidence lookup",
        "/v1/packages/{resource_id}/trust-receipt",
        "package",
    ),
)

assert len(PATHS) == 11, "청사진 §25.6 위임은 정확히 11개 경로를 요구한다"


# ---------------------------------------------------------------------------
# 하니스 픽스처와 헬퍼
# ---------------------------------------------------------------------------


@dataclass
class Harness:
    client: httpx.AsyncClient
    app: Any
    settings: Settings


@dataclass
class TenantBundle:
    tenant_id: uuid.UUID
    email: str
    display_name: str
    user_id: uuid.UUID
    resource_ids: dict[str, uuid.UUID] = field(default_factory=dict)
    markers: list[str] = field(default_factory=list)
    export_payload: bytes = b""


@pytest_asyncio.fixture
async def apath_harness(tmp_path: Path) -> AsyncIterator[Harness]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'apath.db').as_posix()}",
        data_dir=tmp_path / "data",
        local_background_tasks=False,
        test_support_key=_TEST_SUPPORT_KEY,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield Harness(client=client, app=app, settings=settings)


async def _register_tenant(harness: Harness, email: str, tenant_name: str) -> dict[str, Any]:
    """테넌트+소유자를 등록하고 이메일 검증까지 완료한다(기존 fixture 패턴 준수)."""

    response = await harness.client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": _PASSWORD,
            "display_name": tenant_name,
            "tenant_name": tenant_name,
        },
    )
    assert response.status_code == 201, response.text
    captured = await harness.client.post(
        "/__test__/verification-token",
        headers={"X-AKC-Test-Support-Key": _TEST_SUPPORT_KEY},
        json={"email": email},
    )
    assert captured.status_code == 200, captured.text
    verified = await harness.client.post(
        "/v1/auth/verify-email",
        json={"token": captured.json()["token"]},
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


async def _login(harness: Harness, email: str) -> None:
    response = await harness.client.post(
        "/v1/auth/login",
        json={"email": email, "password": _PASSWORD},
    )
    assert response.status_code == 200, response.text


async def _lookup_user_id(harness: Harness, email: str) -> uuid.UUID:
    async with harness.app.state.database.sessions() as session:
        user_id = await session.scalar(select(User.id).where(User.email == email))
    assert user_id is not None
    return uuid.UUID(str(user_id))


async def _seed_resources(harness: Harness, *, tenant_id: uuid.UUID, token: str) -> TenantBundle:
    """한 테넌트의 11경로 측정 대상 자원을 직접 시드한다(읽기 표면만 관찰)."""

    owner_id = await _lookup_user_id(harness, f"owner-{token}@apath.example")
    project_id = uuid.uuid4()
    source_file_id = uuid.uuid4()
    document_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    source_root_id = uuid.uuid4()
    collection_file_id = uuid.uuid4()
    verification_id = uuid.uuid4()
    export_id = uuid.uuid4()
    package_id = uuid.uuid4()

    markers = {
        "project": f"apath-project-secret-{token}",
        "document": f"apath-document-secret-{token}",
        "note": f"apath-note-secret-{token}",
        "collection": f"apath-collection-secret-{token}",
        "proof": f"apath-proof-evidence-{token}",
        "email": f"owner-{token}@apath.example",
    }

    export_payload = f"akc-apath-export-payload-{token}".encode()
    export_sha256 = hashlib.sha256(export_payload).hexdigest()
    storage_key = f"apath/{export_id}.zip"
    # LocalObjectStore는 키를 sha256 샤딩하므로 반드시 스토어 어댑터로 기록한다.
    await harness.app.state.object_store.put_export(storage_key, export_payload)

    async with harness.app.state.database.sessions.begin() as session:
        # 주의: SQLAlchemy UOW가 composite-FK(tenant_id, project_id)→projects 의존을
        # 정렬하지 못해 collections가 projects보다 먼저 INSERT되어 FK가 깨진다
        # (실측 재현). 그래서 부모 행을 명시적으로 먼저 flush한다.
        session.add(
            Project(
                id=project_id,
                tenant_id=tenant_id,
                name=markers["project"],
                created_by=owner_id,
            )
        )
        await session.flush()
        # source_files.upload_id 는 upload_sessions(tenant_id, id)로의 composite
        # FK이므로 업로드 세션 행을 먼저 만든다.
        upload_session_id = uuid.uuid4()
        session.add(
            UploadSession(
                id=upload_session_id,
                tenant_id=tenant_id,
                project_id=project_id,
                document_id=document_id,
                created_by=owner_id,
                original_filename=f"{token}.txt",
                safe_filename=f"{token}.txt",
                expected_mime="text/plain",
                expected_size=32,
                expected_sha256="0" * 64,
                object_key=f"apath-upload-{token}",
                expires_at=utcnow(),
            )
        )
        await session.flush()
        session.add(
            SourceFile(
                id=source_file_id,
                tenant_id=tenant_id,
                project_id=project_id,
                upload_id=upload_session_id,
                original_filename=f"{token}.txt",
                safe_filename=f"{token}.txt",
                mime_type="text/plain",
                size_bytes=32,
                sha256="0" * 64,
                storage_key=f"apath-source-{token}",
                uploaded_by=owner_id,
            )
        )
        await session.flush()
        session.add_all(
            [
                Document(
                    id=document_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    source_file_id=source_file_id,
                    title=markers["document"],
                    document_type="txt",
                    language_codes=["en"],
                    page_count=1,
                    active_version=1,
                    status="PROCESSED",
                ),
                DocumentVersion(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    document_id=document_id,
                    version=1,
                    source_file_id=source_file_id,
                    policy_version="apath-policy",
                    model_revision="apath-model",
                ),
                KnowledgeNote(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    project_id=project_id,
                    document_id=document_id,
                    document_version=1,
                    stable_key=f"apath-{token}",
                    title=markers["note"],
                    note_type="summary",
                    content_markdown=markers["note"],
                    content_origin="compiled",
                ),
                Collection(
                    id=collection_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    name=markers["collection"],
                    status="INGESTED",
                    created_by=owner_id,
                ),
                Export(
                    id=export_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    export_type="vault",
                    status="completed",
                    storage_key=storage_key,
                    sha256=export_sha256,
                    size_bytes=len(export_payload),
                    created_by=owner_id,
                    completed_at=utcnow(),
                ),
            ]
        )
        await session.flush()
        session.add(
            CollectionSourceRoot(
                id=source_root_id,
                tenant_id=tenant_id,
                collection_id=collection_id,
                display_name_ciphertext=b"a" * 32,
                metadata_key_id=_METADATA_KEY_ID,
                source_fingerprint=hashlib.sha256(token.encode()).hexdigest(),
                created_by=owner_id,
            )
        )
        await session.flush()
        session.add(
            CollectionFile(
                id=collection_file_id,
                tenant_id=tenant_id,
                collection_id=collection_id,
                source_root_id=source_root_id,
                relative_path_ciphertext=b"b" * 32,
                display_name_ciphertext=b"c" * 32,
                metadata_key_id=_METADATA_KEY_ID,
                relative_path_blind_index=b"\x00" * 32,
                relative_path_blind_index_key_id=_METADATA_KEY_ID,
                size_bytes=32,
                expected_mime="text/plain",
                sha256="1" * 64,
                status="planned",
            )
        )
        await session.flush()
        session.add_all(
            [
                VerificationRecord(
                    id=verification_id,
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    collection_file_id=collection_file_id,
                    status="verified",
                    validator_revision="apath-validator-v1",
                    evidence={"marker": markers["proof"]},
                ),
                PackageManifest(
                    id=package_id,
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    profile="obsidian",
                    status="completed",
                    manifest_sha256="2" * 64,
                    warnings=[],
                    created_by=owner_id,
                    completed_at=utcnow(),
                ),
            ]
        )

    return TenantBundle(
        tenant_id=tenant_id,
        email=markers["email"],
        display_name=f"APATH Tenant {token.upper()}",
        user_id=owner_id,
        resource_ids={
            "project": project_id,
            "document": document_id,
            "collection": collection_id,
            "verification": verification_id,
            "export": export_id,
            "package": package_id,
        },
        markers=list(markers.values()),
        export_payload=export_payload,
    )


async def _audit_event_count(harness: Harness, tenant_id: uuid.UUID) -> int:
    async with harness.app.state.database.sessions() as session:
        rows = await session.scalars(
            select(AuditEvent.id).where(AuditEvent.tenant_id == tenant_id)
        )
        return len(list(rows))


def _render(path: AccessPath, resource_id: uuid.UUID | None) -> str:
    if path.resource_key is None:
        return path.template
    assert resource_id is not None
    return path.template.replace("{resource_id}", str(resource_id))


# 감사 이벤트 실측치: path_id -> 거부 읽기 중 감사 이벤트가 발행되었는가?
_AUDIT_OBSERVATIONS: dict[str, bool] = {}


# ---------------------------------------------------------------------------
# 핵심 측정: 경로 x (A→B 거부 등가성 + 내용 무누출 + 자기 테넌트 양수 컨트롤)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path_id", "path_under_test"),
    [(path.path_id, path) for path in PATHS],
    ids=[path.path_id for path in PATHS],
)
async def test_access_path_verdict_equivalence(
    path_id: str,
    path_under_test: AccessPath,
    apath_harness: Harness,
) -> None:
    harness = apath_harness

    tenant_a = await _register_tenant(harness, "owner-a@apath.example", "APATH Tenant A")
    tenant_b = await _register_tenant(harness, "owner-b@apath.example", "APATH Tenant B")
    bundle_a = await _seed_resources(
        harness, tenant_id=uuid.UUID(tenant_a["tenant_id"]), token="a"  # noqa: S106
    )
    bundle_b = await _seed_resources(
        harness, tenant_id=uuid.UUID(tenant_b["tenant_id"]), token="b"  # noqa: S106
    )

    # 로그인이 남기는 감사 이벤트 이후를 기준선으로 삼는다.
    await _login(harness, bundle_a.email)
    baseline_audits = await _audit_event_count(harness, bundle_a.tenant_id)

    # --- 1) 미인가 접근: 테넌트 A 주체 → 테넌트 B 자원 -----------------------
    cross_tenant_url = _render(
        path_under_test, bundle_b.resource_ids.get(path_under_test.resource_key)
    )
    denied = await harness.client.get(cross_tenant_url)
    try:
        if path_under_test.resource_key is not None:
            # 자원 식별자 경로: 미인가 접근은 거부(403/404)되어야 한다.
            assert denied.status_code in {403, 404}, (
                f"[{path_id}] 미인가 접근이 거부되지 않았다: "
                f"{denied.status_code} {denied.text[:200]}"
            )
        else:
            # 테넌트 스코프 목록: 식별자가 없으므로 200이 정상이고,
            # 응답은 요청자 테넌트 멤버만 포함해야 한다(아래 누출 검사).
            assert denied.status_code == 200, (
                f"[{path_id}] 스코프 목록 조회 실패: {denied.status_code}"
            )
        for marker in bundle_b.markers:
            assert marker not in denied.text, (
                f"[{path_id}] 거부 응답에 테넌트 B 내용이 누출됨: {marker!r}"
            )

        # --- 2) guessed-UUID 동등성: 실존(B) vs 미존재(무작위) 판정 일치 -------
        if path_under_test.resource_key is not None:
            guessed = await harness.client.get(
                _render(path_under_test, uuid.uuid4())
            )
            assert guessed.status_code == denied.status_code, (
                f"[{path_id}] 자원 존재 여부가 상태 코드로 구별된다: "
                f"B실존={denied.status_code} 무작위={guessed.status_code}"
            )
            for marker in bundle_b.markers:
                assert marker not in guessed.text
    finally:
        after_audits = await _audit_event_count(harness, bundle_a.tenant_id)
        _AUDIT_OBSERVATIONS[path_id] = after_audits > baseline_audits

    # --- 3) 양수 컨트롤: 소유자 자신의 접근은 성공해야 한다 ------------------
    await _login(harness, bundle_b.email)
    own_url = _render(path_under_test, bundle_b.resource_ids.get(path_under_test.resource_key))
    allowed = await harness.client.get(own_url)
    assert allowed.status_code == 200, (
        f"[{path_id}] 자기 테넌트 접근이 실패했다: {allowed.status_code} {allowed.text[:200]}"
    )
    if path_id == "export_download_content":
        assert allowed.content == bundle_b.export_payload
    if path_id == "team_member_roster":
        assert bundle_b.email in allowed.text


# ---------------------------------------------------------------------------
# 감사 이벤트 집계
# ---------------------------------------------------------------------------


async def test_sensitive_read_access_decisions_emit_audit_events() -> None:
    assert len(_AUDIT_OBSERVATIONS) == len(PATHS), (
        "감사 집계는 11경로 측정 테스트가 모두 실행된 뒤에 의미가 있다"
    )
    missing = sorted(
        path_id for path_id, emitted in _AUDIT_OBSERVATIONS.items() if not emitted
    )
    assert not missing, f"민감 읽기 접근 결정이 감사되지 않은 경로: {missing}"


async def test_denied_read_audit_excludes_resource_and_query_secrets(
    apath_harness: Harness,
) -> None:
    harness = apath_harness
    tenant = await _register_tenant(
        harness,
        "audit-minimal@apath.example",
        "Audit Minimal",
    )
    await _login(harness, "audit-minimal@apath.example")
    guessed_id = uuid.uuid4()

    denied = await harness.client.get(
        f"/v1/documents/{guessed_id}?secret=must-not-be-audited"
    )

    assert denied.status_code == 404
    async with harness.app.state.database.sessions() as session:
        event = await session.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == uuid.UUID(tenant["tenant_id"]),
                AuditEvent.action == "security.read_access_denied",
            )
            .order_by(AuditEvent.occurred_at.desc())
        )
    assert event is not None
    assert event.target_id == "/v1/documents/{document_id}"
    serialized = str(event.metadata_json)
    assert str(guessed_id) not in serialized
    assert "must-not-be-audited" not in serialized


async def test_denied_read_fails_closed_when_audit_write_fails(
    apath_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = apath_harness
    await _register_tenant(
        harness,
        "audit-failure@apath.example",
        "Audit Failure",
    )
    await _login(harness, "audit-failure@apath.example")

    async def unavailable_audit(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic audit outage")

    monkeypatch.setattr("akc_api.main.audit", unavailable_audit)
    denied = await harness.client.get(f"/v1/documents/{uuid.uuid4()}")

    assert denied.status_code == 503
    assert denied.json()["error"]["code"] == "AUDIT_WRITE_FAILED"
