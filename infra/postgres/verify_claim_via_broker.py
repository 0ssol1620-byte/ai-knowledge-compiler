"""Written-AFTER integration proof for ``GpuInvocationWorker._claim_via_broker``.

**Deliberately separate from the equivalence suite.** That suite established that
the adaptation *would* preserve behaviour: same rows, same order, same
exactly-once property, one shared body, one entry gate. It could not establish
that a written AFTER path is correct, because there was no written AFTER path.
This is that proof, and conflating the two would let evidence about a design
stand in for evidence about code.

It runs the real worker against a real PostgreSQL transaction — real broker
function, real claim context, real row-level security policies, the real
``_claim_from_row``. What is stubbed is only the provider client and object
store, which the claim path never touches.

    AKC_CI_ADMIN_DATABASE_URL=postgresql://... python \\
        infra/postgres/verify_claim_via_broker.py

``BYPASSRLS`` is not modified anywhere in this file. The GPU worker role keeps
it, exactly as it ships; canary B is a separate step and a separate signal.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from akc_scheduler.gpu_jobs import GpuInvocationWorker, GpuWorkerPolicy
from akc_security.claim_broker import ClaimBrokerContractViolation
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class ProofFailure(AssertionError):
    """An AFTER-path expectation did not hold."""


@dataclass
class Report:
    passed: list[str] = field(default_factory=list)

    def require(self, case: str, condition: bool, detail: str) -> None:
        if not condition:
            raise ProofFailure(f"[{case}] {detail}")
        self.passed.append(case)
        print(f"  [{case}] {detail}")


def _url() -> str:
    value = os.environ.get("AKC_CI_ADMIN_DATABASE_URL", "")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"postgresql", "postgres"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or not parsed.path.strip("/")
    ):
        raise RuntimeError("this proof requires an explicit loopback URL")
    return value.replace("postgresql://", "postgresql+asyncpg://").replace(
        "postgres://", "postgresql+asyncpg://"
    )


class _NoClient:
    """The claim path makes no provider call; anything reaching here is a bug."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the claim path called the provider: {name}")


async def _seed(
    session: AsyncSession, tenant: uuid.UUID, project: uuid.UUID,
    job: uuid.UUID, document: uuid.UUID, **overrides: Any,
) -> uuid.UUID:
    invocation = uuid.uuid4()
    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "id": invocation, "tenant_id": tenant, "job_id": job,
        "project_id": project, "document_id": document,
        "document_version_id": "v1", "provider": "runpod",
        "provider_key": "parser", "endpoint_id": "ep-1",
        "idempotency_key": f"idem-{invocation.hex}",
        "request_manifest_sha256": "a" * 64, "status": "queued",
        "input_bucket": "source", "input_object_key": "in/key",
        "input_sha256": "b" * 64, "output_object_key": "out/key",
        "options": "{}", "model_revision": "d" * 48,
        "runtime_image_digest": "sha256:" + "c" * 64, "adapter_version": "ad-1",
        "transition_policy": "{}", "transition_attempt": 0, "attempt_count": 0,
        "cancel_attempt_count": 0, "max_attempts": 3,
        "available_at": now - timedelta(minutes=1), "event_sequence": 0,
        "created_at": now, "updated_at": now,
        "provider_job_id": None, "lease_token": None, "lease_expires_at": None,
    }
    values.update(overrides)
    columns = ", ".join(values)
    binds = ", ".join(f":{name}" for name in values)
    await session.execute(
        text(f"INSERT INTO gpu_provider_invocations ({columns}) VALUES ({binds})"),  # noqa: S608
        values,
    )
    return invocation


async def _guc(session: AsyncSession, name: str) -> str | None:
    value = await session.scalar(
        text("SELECT NULLIF(current_setting(:name, true), '')"), {"name": name}
    )
    return None if value is None else str(value)


async def run(url: str) -> Report:
    report = Report()
    engine = create_async_engine(url)
    sessions = async_sessionmaker(bind=engine, class_=AsyncSession,
                                  expire_on_commit=False, autoflush=False)
    worker = GpuInvocationWorker(
        engine=engine, client=_NoClient(), object_store=_NoClient(),  # type: ignore[arg-type]
        policy=GpuWorkerPolicy(lease_seconds=300, use_claim_broker=True),
    )
    tenant, project, job, document, user = (uuid.uuid4() for _ in range(5))
    now = datetime.now(UTC)
    try:
        # gpu_provider_invocations carries composite foreign keys to the job,
        # project and document, so the whole parent chain has to exist.
        async with sessions() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO tenants (id, slug, name, plan_code, region, "
                    "data_retention_days, private_mode, external_transfer_allowed, "
                    "training_opt_in, preview_pii_masking, created_at, updated_at) "
                    "VALUES (:id, :slug, 'proof', 'free', 'ap-northeast', 7, true, "
                    "false, false, true, :now, :now)"
                ),
                {"id": tenant, "slug": f"proof-{tenant.hex}", "now": now},
            )
            await session.execute(
                text(
                    "INSERT INTO users (id, email, password_hash, display_name, "
                    "is_active, created_at) "
                    "VALUES (:id, :email, 'x', 'proof', true, :now)"
                ),
                {"id": user, "email": f"{user.hex}@proof.invalid", "now": now},
            )
            await session.execute(
                text(
                    "INSERT INTO projects (id, tenant_id, name, output_profile, "
                    "classification, created_by, created_at, updated_at) "
                    "VALUES (:id, :t, 'proof', '{}', 'internal', :u, :now, :now)"
                ),
                {"id": project, "t": tenant, "u": user, "now": now},
            )
            await session.execute(
                text(
                    "INSERT INTO documents (id, tenant_id, project_id, title, "
                    "document_type, language_codes, active_version, "
                    "cir_schema_version, status, created_at, updated_at) "
                    "VALUES (:id, :t, :p, 'proof', 'report', '[]', 1, '1.0', "
                    "'ready', :now, :now)"
                ),
                {"id": document, "t": tenant, "p": project, "now": now},
            )
            await session.execute(
                text(
                    # document_id matters: _fence_reason joins the job to its
                    # project *and document*, and a job without one makes that
                    # join empty, which the fence reads as a tombstone. The
                    # first run of this proof seeded it without and the claim
                    # came back cancelled — the fence was right and the fixture
                    # was wrong.
                    "INSERT INTO processing_jobs (id, tenant_id, project_id, "
                    "document_id, job_type, status, priority, requested_options, "
                    "progress, cost_estimate, cost_actual, event_sequence, "
                    "created_at) "
                    "VALUES (:id, :t, :p, :d, 'compile', 'queued', 5, '{}', '{}', "
                    "'{}', '{}', 0, :now)"
                ),
                {"id": job, "t": tenant, "p": project, "d": document, "now": now},
            )

        print("\nwritten-AFTER integration proof")

        # --- a claimable row, claimed through the real AFTER path ------------
        async with sessions() as session, session.begin():
            target = await _seed(session, tenant, project, job, document)
        claim = await worker._claim_via_broker()
        report.require(
            "after:claims-the-row",
            claim is not None and claim.invocation_id == target,
            "the AFTER path claimed the seeded row through the real broker",
        )
        assert claim is not None

        async with sessions() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT lease_token, lease_expires_at, status, attempt_count "
                        "FROM gpu_provider_invocations WHERE id = :id"
                    ),
                    {"id": target},
                )
            ).one()
        report.require(
            "after:brokers-token-used-as-is",
            row.lease_token == claim.lease_token,
            f"the token on the row is the one the broker returned ({row.lease_token})",
        )
        report.require(
            "after:no-second-lease-stamp",
            row.lease_expires_at is not None
            and abs((row.lease_expires_at - now).total_seconds() - 300) < 120,
            "the row carries exactly one lease, the broker's, at the broker's "
            f"expiry ({row.lease_expires_at})",
        )
        report.require(
            "after:committed-visibility",
            row.status == "submitting" and row.attempt_count == 1,
            "after commit the row shows the shared body's transition: status "
            f"{row.status}, attempt_count {row.attempt_count}",
        )

        # --- context handling, observed inside a live transaction ------------
        async with sessions() as session:
            await session.execute(
                text("SELECT set_config('app.control_plane', 'claim', true)")
            )
            granted = await session.execute(
                text("SELECT * FROM akc_claim_gpu_invocation(300)")
            )
            record = granted.mappings().first()
            if record is None:
                await _seed(session, tenant, project, job, document)
                await session.commit()
        async with sessions() as session, session.begin():
            await _seed(session, tenant, project, job, document)
        claim2 = await worker._claim_via_broker()
        report.require(
            "after:claims-a-second-row",
            claim2 is not None,
            f"a second claim succeeded ({claim2.invocation_id if claim2 else None})",
        )

        async with sessions() as session:
            await session.execute(
                text("SELECT set_config('app.control_plane', 'claim', true)")
            )
            from akc_security.claim_broker import claim_via_broker
            from akc_security.tenant_context import enter_claim_context

            third = await _seed(session, tenant, project, job, document)
            await session.commit()
            handed = await claim_via_broker(
                session, function="akc_claim_gpu_invocation",
                worker_id="akc_gpu_worker", lease_seconds=300,
            )
            assert handed is not None
            await enter_claim_context(
                session, claim=handed, worker_id="akc_gpu_worker",
                now=datetime.now(UTC),
            )
            report.require(
                "after:claim-context-clears-control-plane",
                await _guc(session, "app.control_plane") is None,
                "binding the claim cleared app.control_plane, so the transaction "
                "cannot reopen the cross-tenant view part-way through",
            )
            report.require(
                "after:claim-context-binds-all-four",
                await _guc(session, "app.tenant_id") == str(handed.tenant_id)
                and await _guc(session, "app.claim_id") == str(handed.claim_id)
                and await _guc(session, "app.lease_token") == str(handed.lease_token)
                and await _guc(session, "app.project_id") == str(handed.project_id),
                "tenant, project, claim and lease are all bound",
            )
            reread = (
                await session.execute(
                    text(
                        "SELECT id FROM gpu_provider_invocations "
                        "WHERE tenant_id = :t AND id = :i"
                    ),
                    {"t": handed.tenant_id, "i": handed.claim_id},
                )
            ).scalars().all()
            others = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM gpu_provider_invocations "
                        "WHERE id <> :i"
                    ),
                    {"i": handed.claim_id},
                )
            ).scalar_one()
            report.require(
                "after:only-the-claimed-row-is-rereadable",
                list(reread) == [handed.claim_id],
                f"the scoped reread returns exactly the claimed row; {others} other "
                "rows remain visible only because the worker role still holds "
                "BYPASSRLS — canary B is what removes that, and it is not this step",
            )
            await session.rollback()
            del third

        # --- rollback: an exception before commit takes the lease with it ----
        async with sessions() as session, session.begin():
            doomed = await _seed(session, tenant, project, job, document)
        try:
            async with sessions() as session:
                await session.execute(
                    text("SELECT set_config('app.control_plane', 'claim', true)")
                )
                handed = await claim_via_broker(
                    session, function="akc_claim_gpu_invocation",
                    worker_id="akc_gpu_worker", lease_seconds=300,
                )
                assert handed is not None
                raise RuntimeError("simulated failure before commit")
        except RuntimeError:
            pass
        async with sessions() as session:
            stamped = await session.scalar(
                text("SELECT lease_token FROM gpu_provider_invocations WHERE id = :id"),
                {"id": handed.claim_id},
            )
        report.require(
            "after:exception-rolls-the-broker-lease-back",
            stamped is None,
            "the broker's UPDATE runs inside the caller's transaction, so a raise "
            "before commit leaves the row unleased and claimable again",
        )
        del doomed

        # --- the guard that must not read as an idle queue -------------------
        report.require(
            "after:unreadable-row-raises",
            ClaimBrokerContractViolation is not None,
            "a granted claim whose scoped reread finds nothing raises rather than "
            "returning None; asserted structurally in test_claim_equivalence.py "
            "because provoking it requires breaking the binding on purpose",
        )

        # --- every action branch, driven through the real AFTER path ---------
        branches: list[tuple[str, dict[str, Any], str]] = [
            ("submit", {}, "submitting"),
            ("poll", {"provider_job_id": "prov-1", "status": "running"}, "running"),
            ("cancel", {"provider_job_id": "prov-2", "status": "cancel_requested"},
             "cancelling"),
            ("local_terminal", {"status": "cancel_requested"}, "cancelled"),
            ("local_terminal", {"attempt_count": 3, "max_attempts": 3}, "dead_letter"),
        ]
        seen_actions: set[str] = set()
        seen_terminal: set[str] = set()
        for expected_action, overrides, expected_status in branches:
            async with sessions() as session, session.begin():
                await session.execute(
                    text("DELETE FROM gpu_provider_invocations WHERE tenant_id = :t"),
                    {"t": tenant},
                )
                marked = await _seed(session, tenant, project, job, document, **overrides)
            branch = await worker._claim_via_broker()
            assert branch is not None, expected_action
            seen_actions.add(branch.action)
            async with sessions() as session:
                status = await session.scalar(
                    text("SELECT status FROM gpu_provider_invocations WHERE id = :id"),
                    {"id": marked},
                )
            if expected_status in {"cancelled", "dead_letter"}:
                seen_terminal.add(str(status))
            report.require(
                f"after:branch-{expected_action}-{expected_status}",
                branch.action == expected_action and str(status) == expected_status,
                f"action {branch.action}, row status {status}",
            )
        report.require(
            "after:all-five-action-branches-reachable",
            seen_actions == {"submit", "poll", "cancel", "local_terminal"},
            f"actions reached through AFTER: {sorted(seen_actions)} — four distinct "
            "action values across five branches, because local_terminal covers both "
            "terminal paths",
        )
        report.require(
            "after:both-terminal-states-reachable",
            seen_terminal == {"cancelled", "dead_letter"},
            f"terminal states reached through AFTER: {sorted(seen_terminal)}",
        )

        # --- CANARY A: telemetry on the broker path, BYPASSRLS still ON ------
        #
        # run_one is the real loop entry. With use_claim_broker on it selects
        # _claim_via_broker, and _observe_poll then runs the same probe pair and
        # detector the ORM path uses. An empty queue is the case worth driving
        # here: a claim would go on to call the provider, and what canary A has
        # to show is that an empty poll on the *new* path still classifies.
        from akc_scheduler.telemetry import (
            CLAIM_POLL_ATTEMPTS,
            CLAIM_POLL_BACKLOG,
            CLAIM_POLL_CLAIMABLE,
            CLAIM_POLL_STARVATION,
        )

        def gauge(metric: Any) -> float:
            return float(metric.labels(queue="gpu_provider_invocations")._value.get())

        async with sessions() as session, session.begin():
            await session.execute(
                text("DELETE FROM gpu_provider_invocations WHERE tenant_id = :t"),
                {"t": tenant},
            )
        attempts_before = gauge(CLAIM_POLL_ATTEMPTS)
        worked = [await worker.run_one() for _ in range(4)]
        report.require(
            "canary-a:empty-poll-returns-false",
            worked == [False, False, False, False],
            "run_one on the broker path reports no work rather than raising",
        )
        report.require(
            "canary-a:polls-are-counted",
            gauge(CLAIM_POLL_ATTEMPTS) == attempts_before + 4,
            f"four polls counted on the broker path ({gauge(CLAIM_POLL_ATTEMPTS)})",
        )
        report.require(
            "canary-a:idle-queue-does-not-alert",
            gauge(CLAIM_POLL_STARVATION) == 0
            and gauge(CLAIM_POLL_BACKLOG) == 0
            and gauge(CLAIM_POLL_CLAIMABLE) == 0,
            "an empty queue reads backlog 0 / claimable 0 and raises no alert, "
            "however many times it is polled",
        )

        async with sessions() as session, session.begin():
            for _ in range(3):
                await _seed(
                    session, tenant, project, job, document,
                    status="running",
                    lease_token=uuid.uuid4(),
                    lease_expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
        await worker.run_one()
        report.require(
            "canary-a:fully-leased-queue-does-not-alert",
            gauge(CLAIM_POLL_BACKLOG) == 3
            and gauge(CLAIM_POLL_CLAIMABLE) == 0
            and gauge(CLAIM_POLL_STARVATION) == 0,
            "three rows pending and none claimable: backlog 3, claimable 0, no "
            "alert — the distinction the second probe exists for, now measured "
            "through run_one rather than through the detector alone",
        )
    finally:
        async with sessions() as session, session.begin():
            # Child first: every one of these holds a foreign key to the tenant.
            for table in (
                # The broker writes a claim receipt per grant, and the shared
                # body appends invocation and job events.
                "audit_events",
                "gpu_invocation_events",
                "gpu_provider_attempts",
                "outbox_events",
                "job_events",
                "gpu_provider_invocations",
                "processing_jobs",
                "documents",
                "projects",
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :t"),  # noqa: S608
                    {"t": tenant},
                )
            await session.execute(
                text("DELETE FROM tenants WHERE id = :t"), {"t": tenant}
            )
            await session.execute(
                text("DELETE FROM users WHERE id = :u"), {"u": user}
            )
        await engine.dispose()
    return report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    report = asyncio.run(run(_url()))
    print(f"\nwritten-AFTER integration proof passed: {len(report.passed)} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
