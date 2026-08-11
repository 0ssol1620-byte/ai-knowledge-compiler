"""Failure paths of the claim binding and the control-plane declaration.

The database enforces the same invariants — ``infra/postgres/shadow_validate_
dual_plane.py`` proves it against real policies — but the database only gets a
chance if the application reaches it. These assert the earlier refusal: a worker
holding the wrong lease never issues the query at all.

The success paths are asserted there rather than here, because "the GUC was
set" is not the property that matters; "the row was not visible" is.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from akc_security.tenant_context import (
    CONTROL_PLANE_PURPOSES,
    ControlPlanePurposeRejected,
    TenantContextMismatch,
    TenantContextMissing,
    WorkerClaim,
    WorkerClaimOwnerMismatch,
    WorkerLeaseExpired,
    enter_claim_context,
    enter_control_plane_context,
    enter_tenant_context,
)

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
WORKER = "url-fetcher-7"


class _Dialect:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeHandle:
    """Shaped like ``AsyncConnection``: ``.dialect`` directly, no ``.bind``."""

    def __init__(self, name: str = "postgresql", tenant: str | None = None) -> None:
        self.dialect = _Dialect(name)
        self.statements: list[tuple[str, dict[str, Any]]] = []
        self._tenant = tenant

    async def execute(self, statement: Any, parameters: dict[str, Any]) -> None:
        self.statements.append((str(statement), parameters))

    async def scalar(self, statement: Any, parameters: dict[str, Any]) -> str | None:
        self.statements.append((str(statement), parameters))
        return self._tenant

    def settings(self) -> dict[str, str]:
        return {
            str(parameters["name"]): str(parameters.get("value", ""))
            for _, parameters in self.statements
            if "name" in parameters
        }


def _claim(**overrides: Any) -> WorkerClaim:
    base: dict[str, Any] = {
        "claim_id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "lease_token": uuid.uuid4(),
        "lease_expires_at": NOW + timedelta(minutes=5),
        "claimed_by": WORKER,
    }
    base.update(overrides)
    return WorkerClaim(**base)


async def test_a_live_claim_sets_every_guc_the_policies_read() -> None:
    handle = _FakeHandle()
    claim = _claim()

    applied = await enter_claim_context(
        handle, claim=claim, worker_id=WORKER, now=NOW
    )

    assert applied.applied is True
    assert handle.settings() == {
        "app.tenant_id": str(claim.tenant_id),
        "app.project_id": str(claim.project_id),
        "app.claim_id": str(claim.claim_id),
        "app.lease_token": str(claim.lease_token),
        # Cleared, not left: a transaction doing one tenant's work must not
        # still hold the cross-tenant reach it discovered the work with.
        "app.control_plane": "",
    }
    for statement, _ in handle.statements:
        assert "true" in statement, "every setting must die with the transaction"


async def test_an_expired_lease_refuses() -> None:
    handle = _FakeHandle()
    claim = _claim(lease_expires_at=NOW - timedelta(seconds=1))
    with pytest.raises(WorkerLeaseExpired):
        await enter_claim_context(handle, claim=claim, worker_id=WORKER, now=NOW)
    assert handle.statements == []


async def test_a_lease_expiring_exactly_now_refuses() -> None:
    """The boundary is closed. A lease at its expiry instant is not held."""

    handle = _FakeHandle()
    with pytest.raises(WorkerLeaseExpired):
        await enter_claim_context(
            handle, claim=_claim(lease_expires_at=NOW), worker_id=WORKER, now=NOW
        )


async def test_another_workers_live_lease_refuses() -> None:
    handle = _FakeHandle()
    claim = _claim(claimed_by="gpu-worker-2")
    with pytest.raises(WorkerClaimOwnerMismatch):
        await enter_claim_context(handle, claim=claim, worker_id=WORKER, now=NOW)
    assert handle.statements == []


@pytest.mark.parametrize(
    "field",
    ["claim_id", "tenant_id", "lease_token", "lease_expires_at", "claimed_by"],
)
async def test_a_missing_identifier_refuses(field: str) -> None:
    handle = _FakeHandle()
    empty: Any = "" if field == "claimed_by" else None
    with pytest.raises(TenantContextMissing):
        await enter_claim_context(
            handle, claim=_claim(**{field: empty}), worker_id=WORKER, now=NOW
        )
    assert handle.statements == []


async def test_a_missing_worker_identity_refuses() -> None:
    handle = _FakeHandle()
    with pytest.raises(TenantContextMissing):
        await enter_claim_context(handle, claim=_claim(), worker_id="", now=NOW)


async def test_a_naive_lease_timestamp_refuses_rather_than_comparing() -> None:
    handle = _FakeHandle()
    claim = _claim(lease_expires_at=datetime(2099, 1, 1))
    with pytest.raises(TenantContextMissing):
        await enter_claim_context(handle, claim=claim, worker_id=WORKER, now=NOW)


@pytest.mark.parametrize(
    ("assertion", "field"),
    [
        ("expected_tenant_id", "tenant_id"),
        ("expected_project_id", "project_id"),
        ("expected_claim_id", "claim_id"),
        ("expected_lease_token", "lease_token"),
    ],
)
async def test_a_forged_assertion_refuses(assertion: str, field: str) -> None:
    handle = _FakeHandle()
    with pytest.raises(TenantContextMismatch):
        await enter_claim_context(
            handle,
            claim=_claim(),
            worker_id=WORKER,
            now=NOW,
            **{assertion: uuid.uuid4()},
        )
    assert handle.statements == []


async def test_asserting_a_project_the_claim_does_not_have_refuses() -> None:
    """A claim with no project cannot satisfy an assertion that names one."""

    handle = _FakeHandle()
    with pytest.raises(TenantContextMismatch):
        await enter_claim_context(
            handle,
            claim=_claim(project_id=None),
            worker_id=WORKER,
            now=NOW,
            expected_project_id=uuid.uuid4(),
        )


async def test_a_claim_without_a_project_sets_the_setting_empty() -> None:
    handle = _FakeHandle()
    await enter_claim_context(
        handle, claim=_claim(project_id=None), worker_id=WORKER, now=NOW
    )
    assert handle.settings()["app.project_id"] == ""


async def test_matching_assertions_are_accepted() -> None:
    handle = _FakeHandle()
    claim = _claim()
    applied = await enter_claim_context(
        handle,
        claim=claim,
        worker_id=WORKER,
        now=NOW,
        expected_tenant_id=str(claim.tenant_id),
        expected_project_id=str(claim.project_id),
        expected_claim_id=str(claim.claim_id),
        expected_lease_token=str(claim.lease_token),
    )
    assert applied.claim.claim_id == claim.claim_id


async def test_sqlite_is_reported_not_pretended() -> None:
    handle = _FakeHandle(name="sqlite")
    applied = await enter_claim_context(
        handle, claim=_claim(), worker_id=WORKER, now=NOW
    )
    assert applied.backend == "sqlite"
    assert applied.applied is False
    assert handle.statements == []


async def test_an_unapproved_control_plane_purpose_refuses() -> None:
    handle = _FakeHandle()
    with pytest.raises(ControlPlanePurposeRejected):
        await enter_control_plane_context(handle, purpose="exfiltrate")
    assert handle.statements == []


@pytest.mark.parametrize("purpose", sorted(CONTROL_PLANE_PURPOSES))
async def test_each_approved_purpose_is_declared(purpose: str) -> None:
    handle = _FakeHandle()
    applied = await enter_control_plane_context(handle, purpose=purpose)
    assert applied.applied is True
    assert handle.settings()["app.control_plane"] == purpose


async def test_declaring_a_purpose_after_binding_a_tenant_refuses() -> None:
    """The cross-tenant view cannot be reopened partway through a tenant's work."""

    handle = _FakeHandle(tenant=str(uuid.uuid4()))
    with pytest.raises(ControlPlanePurposeRejected):
        await enter_control_plane_context(handle, purpose="job_discovery")
    assert "app.control_plane" not in handle.settings()


async def test_binding_a_tenant_clears_a_declared_purpose() -> None:
    handle = _FakeHandle()
    await enter_tenant_context(handle, tenant_id=uuid.uuid4())
    assert handle.settings()["app.control_plane"] == ""
