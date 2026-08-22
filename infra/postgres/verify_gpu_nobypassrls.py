"""The complete canary-B proof: the real GPU worker, against a disarmed role.

Every other GPU proof in this repository runs while ``akc_gpu_worker`` holds
``BYPASSRLS``, so none of them observes a policy — a bypassing role makes the
policies unobservable, which is the whole reason the shadow harness exists. This
one runs after the attribute is removed, and it **refuses to run if it was not**.
That refusal is the point: a proof that quietly passes against a bypassing role
would report "canary B is green" having measured nothing.

    AKC_CI_ADMIN_DATABASE_URL=postgresql://... python \\
        infra/postgres/verify_gpu_nobypassrls.py

It does not disarm anything itself. ``infra/postgres/canary_b_disarm.py`` is the
operation that removes the attribute, runs this, and restores it on failure;
running this file alone against an armed cluster is expected to fail at the first
guard, and that is a useful thing to try.

**Four classifications, from the access-site matrix.** Each case names which one
it is exercising, because they are authorized by different mechanisms and a proof
that blurs them proves the wrong thing:

* **DISCOVERY** — before any row is known. No tenant exists to bind, so the
  authorization is the broker's declared control-plane purpose, and the worker's
  own cross-tenant read is expected to see *nothing*.
* **ACTIVE CLAIM** — a lease is held. ``enter_claim_context`` binds tenant,
  project, row and lease token, and the claim binding admits exactly that row.
* **CALLBACK / LEASE-INDEPENDENT** — no lease exists to bind, because it was
  released when the job was handed to the provider. ``enter_callback_context``
  binds tenant, project and row.
* **OTHER** — observability probes, which read counts and no rows.

**Negative controls are not decoration here.** Roughly half these cases assert
that something is *refused*: the pre-fix tenant-only binding sees nothing, a
forged lease token sees nothing, a second row is unreachable, a lease handoff is
rejected. Without them a misconfiguration that left RLS off entirely would pass
every positive case in this file.

Two cases are named ``gap:`` and assert that a path is **broken**. They are
measurements of known defects that canary B does not cause and does not fix, and
they are written as assertions so that fixing one turns this file red rather than
letting the matrix quietly go stale.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import asyncpg  # type: ignore[import-untyped]
from akc_api.gpu_provider import GpuJobPoll, GpuJobResult, SubmittedGpuJob
from akc_api.storage import UploadTarget
from akc_scheduler.gpu_jobs import GpuInvocationWorker, GpuWorkerPolicy
from akc_security.claim_broker import resolve_callback_target
from akc_security.tenant_context import (
    WorkerCallback,
    WorkerClaim,
    WorkerLeaseExpired,
    enter_callback_context,
    enter_claim_context,
    enter_tenant_context,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

CANARY_ROLE = "akc_gpu_worker"
CLAIM_BROKER = "akc_claim_gpu_invocation"
CALLBACK_RESOLVER = "akc_resolve_gpu_callback"
EXPECTED_ARMED_AFTER_DISARM = 6

#: The login principal this proof connects as. Created if absent, granted only
#: ``akc_gpu_worker``, and left with no password when the run ends. One
#: membership, deliberately: ``SET ROLE`` is checked against the *session* user's
#: memberships, so a principal holding two worker roles would prove something
#: weaker than it claimed — a rule the shadow harness learned by failing.
PROOF_LOGIN = "akc_gpu_proof_runtime"


class ProofFailure(AssertionError):
    """A canary-B expectation did not hold."""


class ProofRefused(RuntimeError):
    """The cluster is not in a state where this proof would measure anything."""


@dataclass
class Report:
    passed: list[str] = field(default_factory=list)

    def require(self, case: str, condition: bool, detail: str) -> None:
        if not condition:
            raise ProofFailure(f"[{case}] {detail}")
        self.passed.append(case)
        print(f"  [{case}] {detail}", flush=True)


def _admin_url() -> str:
    value = os.environ.get("AKC_CI_ADMIN_DATABASE_URL", "")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"postgresql", "postgres"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or not parsed.path.strip("/")
    ):
        raise ProofRefused("this proof requires an explicit loopback URL")
    return value


def _worker_url(admin: str, password: str) -> str:
    parsed = urlsplit(admin)
    host = parsed.hostname or "127.0.0.1"
    port = f":{parsed.port}" if parsed.port else ""
    database = parsed.path.strip("/")
    return (
        f"postgresql+asyncpg://{PROOF_LOGIN}:{password}@{host}{port}/{database}"
    )


class _StubStore:
    """Object storage, reduced to what the claim and admission paths ask of it.

    The proof is about database authorization; the object store is upstream of
    every statement it measures and downstream of none.
    """

    def __init__(self) -> None:
        self.body = b""

    async def create_gpu_input_target(self, *, object_key: str, **_: Any) -> UploadTarget:
        # GpuJobRequest checks the URL path against the object key and the key
        # against the tenant prefix, so a placeholder URL fails validation and
        # the failure surfaces as a provider error four frames away.
        return UploadTarget(url=f"https://proof.invalid/{object_key}", headers={})

    async def create_gpu_output_target(self, *, object_key: str, **_: Any) -> UploadTarget:
        return UploadTarget(url=f"https://proof.invalid/{object_key}", headers={})

    async def read_derived(self, _key: str) -> bytes:
        return self.body


class _StubClient:
    """A provider that does exactly what the next case needs and records nothing."""

    def __init__(self) -> None:
        self.poll: GpuJobPoll | None = None
        self.submitted = SubmittedGpuJob(
            provider_job_id="prov-proof", endpoint_id="ep-1", status="IN_QUEUE"
        )
        self.fail_submit: Exception | None = None

    async def submit(self, _request: Any) -> SubmittedGpuJob:
        if self.fail_submit is not None:
            raise self.fail_submit
        return self.submitted

    async def poll_once(self, _request: Any, _submitted: Any) -> GpuJobPoll:
        assert self.poll is not None, "the proof did not stage a poll observation"
        return self.poll

    async def cancel(self, _submitted: Any) -> None:
        return None


@dataclass
class _Fixture:
    tenant: uuid.UUID
    project: uuid.UUID
    job: uuid.UUID
    document: uuid.UUID
    user: uuid.UUID


async def _seed_parents(admin: asyncpg.Connection) -> _Fixture:
    """gpu_provider_invocations carries composite keys to the whole chain."""

    fixture = _Fixture(*(uuid.uuid4() for _ in range(5)))
    now = datetime.now(UTC)
    await admin.execute(
        "INSERT INTO tenants (id, slug, name, plan_code, region,"
        " data_retention_days, private_mode, external_transfer_allowed,"
        " training_opt_in, preview_pii_masking, created_at, updated_at)"
        " VALUES ($1,$2,'canary-b','free','ap-northeast',7,true,false,false,true,$3,$3)",
        fixture.tenant, f"canary-b-{fixture.tenant.hex}", now,
    )
    await admin.execute(
        "INSERT INTO users (id, email, password_hash, display_name, is_active,"
        " created_at) VALUES ($1,$2,'x','canary-b',true,$3)",
        fixture.user, f"{fixture.user.hex}@canary.invalid", now,
    )
    await admin.execute(
        "INSERT INTO projects (id, tenant_id, name, output_profile, classification,"
        " created_by, created_at, updated_at)"
        " VALUES ($1,$2,'canary-b','{}','internal',$3,$4,$4)",
        fixture.project, fixture.tenant, fixture.user, now,
    )
    await admin.execute(
        "INSERT INTO documents (id, tenant_id, project_id, title, document_type,"
        " language_codes, active_version, cir_schema_version, status, created_at,"
        " updated_at) VALUES ($1,$2,$3,'canary-b','report','[]',1,'1.0','ready',$4,$4)",
        fixture.document, fixture.tenant, fixture.project, now,
    )
    await admin.execute(
        "INSERT INTO processing_jobs (id, tenant_id, project_id, document_id,"
        " job_type, status, priority, requested_options, progress, cost_estimate,"
        " cost_actual, event_sequence, created_at)"
        " VALUES ($1,$2,$3,$4,'compile','queued',5,'{}','{}','{}','{}',0,$5)",
        fixture.job, fixture.tenant, fixture.project, fixture.document, now,
    )
    return fixture


async def _seed_invocation(
    admin: asyncpg.Connection, fixture: _Fixture, **overrides: Any
) -> uuid.UUID:
    invocation = uuid.uuid4()
    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "id": invocation, "tenant_id": fixture.tenant, "job_id": fixture.job,
        "project_id": fixture.project, "document_id": fixture.document,
        "document_version_id": "v1", "provider": "runpod", "provider_key": "parser",
        "endpoint_id": "ep-1", "idempotency_key": f"idem-{invocation.hex}",
        "request_manifest_sha256": "a" * 64, "status": "queued",
        "input_bucket": "source",
        "input_object_key": f"tenants/{fixture.tenant}/source/in.bin",
        "input_sha256": "b" * 64,
        "output_object_key": f"tenants/{fixture.tenant}/derived/out.json",
        "options": "{}",
        "model_revision": "d" * 48, "runtime_image_digest": "sha256:" + "c" * 64,
        "adapter_version": "ad-1", "transition_policy": "{}", "transition_attempt": 0,
        "attempt_count": 0, "cancel_attempt_count": 0, "max_attempts": 3,
        "available_at": now - timedelta(minutes=1), "event_sequence": 0,
        "created_at": now, "updated_at": now,
    }
    values.update(overrides)
    columns = ", ".join(values)
    binds = ", ".join(f"${index + 1}" for index in range(len(values)))
    await admin.execute(
        f"INSERT INTO gpu_provider_invocations ({columns}) VALUES ({binds})",  # noqa: S608
        *values.values(),
    )
    return invocation


async def _clear_invocations(admin: asyncpg.Connection, fixture: _Fixture) -> None:
    for table in ("gpu_invocation_events", "gpu_provider_attempts",
                  "gpu_provider_invocations"):
        await admin.execute(
            f"DELETE FROM {table} WHERE tenant_id = $1", fixture.tenant  # noqa: S608
        )


async def _guc(session: AsyncSession, name: str) -> str | None:
    value = await session.scalar(
        text("SELECT NULLIF(current_setting(:name, true), '')"), {"name": name}
    )
    return None if value is None else str(value)


async def _visible(sessions: Any, bound: dict[str, str], invocation_id: uuid.UUID) -> int:
    """Count what one raw GUC binding can read, without going through the helpers.

    ``enter_claim_context`` refuses an expired lease before it reaches the
    database, so a claim context is the wrong instrument for asking whether the
    *database* refuses one. This sets the four settings by hand and asks.
    """

    async with sessions() as session:
        for name, value in bound.items():
            await session.execute(
                text("SELECT set_config(:n, :v, true)"), {"n": name, "v": value}
            )
        seen = await session.scalar(
            text("SELECT count(*) FROM gpu_provider_invocations WHERE id = :i"),
            {"i": invocation_id},
        )
    return int(seen or 0)


def _result_for(claim: Any, body_metrics: dict[str, Any]) -> tuple[GpuJobResult, bytes]:
    """A provider result and the object body that attests to it, agreeing."""

    payload = {
        "schema_version": "1.0",
        "result_id": "res-proof",
        "job_id": str(claim.job_id),
        "tenant_id": str(claim.tenant_id),
        "provider": claim.provider_key,
        "model_revision": claim.model_revision,
        "runtime_image_digest": claim.runtime_image_digest,
        "adapter_version": claim.adapter_version,
        "input_sha256": f"sha256:{claim.input_sha256}",
        "idempotency_key": claim.idempotency_key,
        "worker_kind": "parser",
        "metrics": body_metrics,
        "warnings": [],
    }
    body = json.dumps(payload).encode("utf-8")
    result = GpuJobResult(
        provider_job_id="prov-proof",
        endpoint_id=claim.endpoint_id,
        provider_key=claim.provider_key,
        model_revision=claim.model_revision,
        runtime_image_digest=claim.runtime_image_digest,
        adapter_version=claim.adapter_version,
        result_id="res-proof",
        output_object_key=claim.output_object_key,
        output_sha256=hashlib.sha256(body).hexdigest(),
        output_bytes=len(body),
        metrics=body_metrics,
        warnings=(),
        # 71 characters, prefix included: gpu_provider_attempts constrains the
        # length rather than the alphabet.
        raw_provider_response_sha256="sha256:" + "e" * 64,
    )
    return result, body


async def _guard(admin: asyncpg.Connection, report: Report) -> None:
    """Refuse to measure a cluster that would make every case vacuous."""

    bypassing = await admin.fetchval(
        "SELECT rolbypassrls FROM pg_roles WHERE rolname = $1", CANARY_ROLE
    )
    if bypassing is None:
        raise ProofRefused(f"{CANARY_ROLE} does not exist")
    if bypassing:
        raise ProofRefused(
            f"{CANARY_ROLE} still holds BYPASSRLS. Every policy this proof exists "
            "to measure is bypassed, so a pass would mean nothing. Run "
            "infra/postgres/canary_b_disarm.py, which disarms and then runs this."
        )
    report.require(
        "guard:canary-role-is-disarmed",
        True,
        f"{CANARY_ROLE} is NOBYPASSRLS, so the policies below are in force",
    )
    armed = [
        str(row["rolname"])
        for row in await admin.fetch(
            r"SELECT rolname FROM pg_roles WHERE rolname LIKE 'akc\_%' ESCAPE '\'"
            " AND rolbypassrls ORDER BY rolname"
        )
    ]
    report.require(
        "guard:six-worker-roles-remain-armed",
        len(armed) == EXPECTED_ARMED_AFTER_DISARM and CANARY_ROLE not in armed,
        f"canary B is one role: {len(armed)} still armed ({', '.join(armed)})",
    )
    # The broker is cross-tenant by construction, so a row left behind by
    # anything else is a row this proof can be handed instead of its own. The
    # first draft of this file was, and spent a case asserting the wrong
    # project. An empty queue is a precondition, not a nicety.
    strays = await admin.fetchval("SELECT count(*) FROM gpu_provider_invocations")
    if strays:
        raise ProofRefused(
            f"gpu_provider_invocations holds {strays} row(s) this proof did not "
            "seed. The broker would hand them to the worker under test, so the "
            "queue must be empty before it starts."
        )
    report.require(
        "guard:the-queue-holds-nothing-this-proof-did-not-seed",
        True,
        "every row claimed below is one this file put there",
    )


async def run(admin_url: str) -> Report:
    report = Report()
    admin = await asyncpg.connect(admin_url)
    password = secrets.token_urlsafe(32)
    engine = None
    provisioned = False
    try:
        # Before anything is created, so a refusal leaves the cluster exactly as
        # it was found rather than half prepared.
        await _guard(admin, report)
        # The only interpolated value is a module constant naming this file's own
        # throwaway login principal; there is no caller input in this statement.
        await admin.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname ="  # noqa: S608
            f" '{PROOF_LOGIN}') THEN CREATE ROLE {PROOF_LOGIN} LOGIN NOINHERIT"
            f" NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;"
            f" END IF; END $$"
        )
        await admin.execute(f"ALTER ROLE {PROOF_LOGIN} PASSWORD '{password}'")
        await admin.execute(f"GRANT {CANARY_ROLE} TO {PROOF_LOGIN}")
        provisioned = True

        engine = create_async_engine(
            _worker_url(admin_url, password),
            connect_args={"server_settings": {"role": CANARY_ROLE}},
        )
        sessions = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
        )
        store = _StubStore()
        client = _StubClient()
        worker = GpuInvocationWorker(
            engine=engine,
            client=client,  # type: ignore[arg-type]
            object_store=store,  # type: ignore[arg-type]
            policy=GpuWorkerPolicy(lease_seconds=300, use_claim_broker=True),
        )

        async with sessions() as session:
            identity = (
                await session.execute(
                    text(
                        "SELECT current_user AS effective, session_user AS login,"
                        " (SELECT rolbypassrls FROM pg_roles"
                        "  WHERE rolname = current_user) AS bypass"
                    )
                )
            ).one()
        report.require(
            "guard:worker-runs-as-the-canary-role",
            identity.effective == CANARY_ROLE
            and identity.login == PROOF_LOGIN
            and identity.bypass is False,
            f"the worker's own engine authorizes as {identity.effective} "
            f"(login {identity.login}), BYPASSRLS {identity.bypass} - the same "
            "role and the same pinning create_gpu_engine applies in production",
        )

        fixture = await _seed_parents(admin)
        print("\ncanary B - DISCOVERY", flush=True)

        # ------------------------------------------------------------------
        # DISCOVERY. No row is known yet, so no tenant can be bound.
        # ------------------------------------------------------------------
        for _ in range(3):
            await _seed_invocation(admin, fixture)
        claimable = await admin.fetchval(
            "SELECT count(*) FROM gpu_provider_invocations WHERE tenant_id = $1",
            fixture.tenant,
        )
        report.require(
            "discovery:the-queue-is-not-empty",
            claimable == 3,
            f"an admin sees {claimable} claimable rows, so the two reads below "
            "are measuring visibility rather than an empty queue",
        )

        async with sessions() as session:
            unscoped = await session.scalar(
                text("SELECT count(*) FROM gpu_provider_invocations")
            )
        report.require(
            "discovery:no-cross-tenant-read-without-context",
            unscoped == 0,
            f"the worker's own unscoped read of the queue returns {unscoped} of "
            f"{claimable} rows",
        )

        async with sessions() as session:
            before_path = await session.scalar(
                text(
                    "SELECT count(*) FROM gpu_provider_invocations"
                    " WHERE status IN ('queued','submitting','submitted','running',"
                    "'retry','cancel_requested','cancelling')"
                    "   AND available_at <= now()"
                    "   AND (lease_expires_at IS NULL OR lease_expires_at <= now())"
                )
            )
        report.require(
            "discovery:before-path-claim-scan-sees-nothing",
            before_path == 0,
            f"GpuWorkerPolicy.use_claim_broker=False selects the ORM scan, which "
            f"returns {before_path} of {claimable} claimable rows here. **Canary A "
            "is a precondition of canary B**: with the broker off, a disarmed "
            "worker claims nothing at all",
        )

        first = await worker._claim_via_broker()
        report.require(
            "discovery:broker-grants-a-claim-to-a-disarmed-worker",
            first is not None,
            f"the broker granted {first.invocation_id if first else None}; the "
            "definer function reaches the queue the worker cannot",
        )
        assert first is not None
        stamped = await admin.fetchrow(
            "SELECT project_id, lease_token, lease_expires_at FROM"
            " gpu_provider_invocations WHERE id = $1",
            first.invocation_id,
        )
        report.require(
            "discovery:claim-carries-the-rows-project-and-expiry",
            first.project_id == stamped["project_id"]
            and first.lease_token == stamped["lease_token"]
            and first.lease_expires_at == stamped["lease_expires_at"],
            f"_Claim carries project {first.project_id}, token {first.lease_token} "
            f"and expiry {first.lease_expires_at} - compared against the row rather "
            "than against what the proof expected, because the requirement is that "
            "they are populated *truthfully*, not that they are populated",
        )

        print("\ncanary B - ACTIVE CLAIM", flush=True)

        # ------------------------------------------------------------------
        # ACTIVE CLAIM. A lease is held; the binding is the authorization.
        # ------------------------------------------------------------------
        async with sessions() as session:
            locked = await worker._locked_invocation(session, first)
            bound = {
                name: await _guc(session, name)
                for name in ("app.tenant_id", "app.project_id", "app.claim_id",
                             "app.lease_token", "app.callback_id",
                             "app.control_plane")
            }
        report.require(
            "claim:locked-invocation-reads-its-row",
            locked is not None and locked.id == first.invocation_id,
            "_locked_invocation returned the claimed row under a disarmed role",
        )
        report.require(
            "claim:locked-invocation-binds-all-four",
            bound["app.tenant_id"] == str(first.tenant_id)
            and bound["app.project_id"] == str(first.project_id)
            and bound["app.claim_id"] == str(first.invocation_id)
            and bound["app.lease_token"] == str(first.lease_token)
            and bound["app.callback_id"] is None
            and bound["app.control_plane"] is None,
            "tenant, project, claim and lease are bound; the callback and "
            "control-plane settings are cleared, so no second plane is open",
        )

        async with sessions() as session:
            await enter_tenant_context(session, tenant_id=first.tenant_id)
            tenant_only = await session.scalar(
                text(
                    "SELECT count(*) FROM gpu_provider_invocations"
                    " WHERE tenant_id = :t AND id = :i"
                ),
                {"t": first.tenant_id, "i": first.invocation_id},
            )
        report.require(
            "claim:tenant-only-binding-still-sees-nothing",
            tenant_only == 0,
            f"the binding _locked_invocation used before this change returns "
            f"{tenant_only} rows for a row the claim-bound session can read - the "
            "measured cause of the abandoned-claim failure, reproduced here",
        )

        second = await worker._claim_via_broker()
        assert second is not None
        async with sessions() as session:
            await enter_claim_context(
                session,
                claim=WorkerClaim(
                    claim_id=first.invocation_id, tenant_id=first.tenant_id,
                    project_id=first.project_id, lease_token=first.lease_token,
                    lease_expires_at=first.lease_expires_at, claimed_by=CANARY_ROLE,
                ),
                worker_id=CANARY_ROLE,
                now=datetime.now(UTC),
            )
            neighbour = await session.scalar(
                text("SELECT count(*) FROM gpu_provider_invocations WHERE id = :i"),
                {"i": second.invocation_id},
            )
            own = await session.scalar(
                text("SELECT count(*) FROM gpu_provider_invocations WHERE id = :i"),
                {"i": first.invocation_id},
            )
        report.require(
            "claim:a-second-claimed-row-is-unreachable",
            neighbour == 0 and own == 1,
            "holding one claim, the worker sees its own row and not the other "
            "live claim in the same tenant and project",
        )

        async with sessions() as session:
            await enter_claim_context(
                session,
                claim=WorkerClaim(
                    claim_id=first.invocation_id, tenant_id=first.tenant_id,
                    project_id=first.project_id, lease_token=uuid.uuid4(),
                    lease_expires_at=first.lease_expires_at, claimed_by=CANARY_ROLE,
                ),
                worker_id=CANARY_ROLE,
                now=datetime.now(UTC),
            )
            forged = await session.scalar(
                text("SELECT count(*) FROM gpu_provider_invocations WHERE id = :i"),
                {"i": first.invocation_id},
            )
        report.require(
            "claim:a-forged-lease-token-reads-nothing",
            forged == 0,
            "a well-formed context naming a lease the row does not carry sees "
            "nothing; the token is compared at the database, not only in Python",
        )

        expired = False
        try:
            async with sessions() as session:
                await enter_claim_context(
                    session,
                    claim=WorkerClaim(
                        claim_id=first.invocation_id, tenant_id=first.tenant_id,
                        project_id=first.project_id, lease_token=first.lease_token,
                        lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
                        claimed_by=CANARY_ROLE,
                    ),
                    worker_id=CANARY_ROLE,
                    now=datetime.now(UTC),
                )
        except WorkerLeaseExpired:
            expired = True
        report.require(
            "claim:an-expired-lease-never-reaches-the-database",
            expired,
            "enter_claim_context refuses before it sets anything, so an expired "
            "lease cannot leave a tenant bound with no claim",
        )

        handoff: str | None = None
        try:
            async with sessions() as session, session.begin():
                await enter_claim_context(
                    session,
                    claim=WorkerClaim(
                        claim_id=first.invocation_id, tenant_id=first.tenant_id,
                        project_id=first.project_id, lease_token=first.lease_token,
                        lease_expires_at=first.lease_expires_at,
                        claimed_by=CANARY_ROLE,
                    ),
                    worker_id=CANARY_ROLE,
                    now=datetime.now(UTC),
                )
                await session.execute(
                    text(
                        "UPDATE gpu_provider_invocations SET lease_token = :new"
                        " WHERE id = :i"
                    ),
                    {"new": uuid.uuid4(), "i": first.invocation_id},
                )
        except DBAPIError as error:
            handoff = str(getattr(error.orig, "sqlstate", "")) or type(error).__name__
        report.require(
            "claim:a-lease-handoff-is-refused",
            handoff == "42501",
            f"writing a different lease token onto the claimed row fails the "
            f"claim binding's WITH CHECK ({handoff}); the release disjunct admits "
            "no lease, never another worker's",
        )

        print("\ncanary B - ACTIVE CLAIM, through run_one", flush=True)

        await _clear_invocations(admin, fixture)
        submit_target = await _seed_invocation(admin, fixture)
        client.poll = None
        worked = await worker.run_one()
        row = await admin.fetchrow(
            "SELECT status, provider_job_id, lease_token, lease_expires_at IS NULL"
            " AS released, attempt_count, last_error_code FROM"
            " gpu_provider_invocations WHERE id = $1",
            submit_target,
        )
        report.require(
            "claim:run-one-submits-and-releases-the-lease",
            worked
            and row["status"] == "submitted"
            and row["provider_job_id"] == "prov-proof"
            and row["released"]
            and row["lease_token"] is not None
            and row["attempt_count"] == 1,
            f"the real loop claimed, submitted and released: status {row['status']}, "
            f"provider job {row['provider_job_id']}, lease cleared {row['released']} "
            f"with its token kept, error {row['last_error_code']}. The release is "
            "the write the 0034 predicate refused, and keeping the token is what "
            "stops the release admitting rows nobody claimed",
        )

        async with sessions() as session:
            await enter_claim_context(
                session,
                claim=WorkerClaim(
                    claim_id=submit_target, tenant_id=fixture.tenant,
                    project_id=fixture.project, lease_token=uuid.uuid4(),
                    lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
                    claimed_by=CANARY_ROLE,
                ),
                worker_id=CANARY_ROLE,
                now=datetime.now(UTC),
            )
            stranger = await session.scalar(
                text("SELECT count(*) FROM gpu_provider_invocations WHERE id = :i"),
                {"i": submit_target},
            )
        report.require(
            "claim:a-released-row-is-not-readable-without-its-token",
            stranger == 0,
            "naming a released row's id without its lease token reads nothing. "
            "The rejected alternative - admitting lease_token IS NULL - made this "
            "return the row, and made it writable too",
        )

        # Released and lapsed, on one row, with one token, one statement apart.
        # This is the pair that chose the shape: `lease_expires_at <= now()` also
        # made the release write succeed, but it admitted both of these, and a
        # lapsed lease means this worker has been superseded.
        held_token = await admin.fetchval(
            "SELECT lease_token FROM gpu_provider_invocations WHERE id = $1",
            submit_target,
        )
        bound = {
            "app.tenant_id": str(fixture.tenant),
            "app.project_id": str(fixture.project),
            "app.claim_id": str(submit_target),
            "app.lease_token": str(held_token),
        }
        released_seen = await _visible(sessions, bound, submit_target)
        await admin.execute(
            "UPDATE gpu_provider_invocations SET lease_expires_at = now() -"
            " interval '5 minutes' WHERE id = $1",
            submit_target,
        )
        lapsed_seen = await _visible(sessions, bound, submit_target)
        await admin.execute(
            "UPDATE gpu_provider_invocations SET lease_expires_at = NULL WHERE id = $1",
            submit_target,
        )
        report.require(
            "claim:a-lapsed-lease-is-refused-where-a-released-one-is-admitted",
            released_seen == 1 and lapsed_seen == 0,
            f"the holder reads its released row ({released_seen}) and stops reading "
            f"it the moment the same row carries a lapsed expiry instead "
            f"({lapsed_seen}). enter_claim_context refuses an expired lease in "
            "Python too; this is the database saying so on its own, which is what "
            "shadow_validate_dual_plane's claim:expired-lease case requires",
        )

        await admin.execute(
            "UPDATE gpu_provider_invocations SET available_at = now() -"
            " interval '1 minute' WHERE id = $1",
            submit_target,
        )
        client.poll = GpuJobPoll(status="IN_PROGRESS", result=None)
        worked = await worker.run_one()
        row = await admin.fetchrow(
            "SELECT status, lease_expires_at IS NULL AS released FROM"
            " gpu_provider_invocations WHERE id = $1",
            submit_target,
        )
        report.require(
            "claim:run-one-records-a-poll-wait",
            worked and row["status"] == "running" and row["released"],
            f"a non-terminal poll wrote status {row['status']} and released the "
            "lease again",
        )

        await admin.execute(
            "UPDATE gpu_provider_invocations SET available_at = now() -"
            " interval '1 minute' WHERE id = $1",
            submit_target,
        )
        pending = await worker._claim_via_broker()
        assert pending is not None
        result, body = _result_for(pending, {"gpu_seconds": 1.0})
        store.body = body
        admitted = await worker._admit_result(
            pending, result, body, source="poll"
        )
        row = await admin.fetchrow(
            "SELECT status, completion_source, result_manifest_sha256,"
            " lease_expires_at IS NULL AS released FROM gpu_provider_invocations"
            " WHERE id = $1",
            submit_target,
        )
        report.require(
            "claim:run-one-admits-a-terminal-result",
            admitted
            and row["status"] == "completed"
            and row["completion_source"] == "poll"
            and row["result_manifest_sha256"] is not None
            and row["released"],
            f"admission wrote status {row['status']}, source "
            f"{row['completion_source']} and a manifest hash, all through the "
            "claim-bound _locked_invocation",
        )

        await _clear_invocations(admin, fixture)
        failing = await _seed_invocation(admin, fixture)
        client.fail_submit = RuntimeError("provider unreachable")
        worked = await worker.run_one()
        client.fail_submit = None
        row = await admin.fetchrow(
            "SELECT status, last_error_code, lease_expires_at IS NULL AS released"
            " FROM gpu_provider_invocations WHERE id = $1",
            failing,
        )
        report.require(
            "claim:run-one-records-a-failure",
            worked
            and row["status"] in {"retry", "failed", "dead_letter"}
            and row["last_error_code"] is not None
            and row["released"],
            f"a failed submission wrote status {row['status']}, code "
            f"{row['last_error_code']} and released the lease",
        )

        await _clear_invocations(admin, fixture)
        cancelling = await _seed_invocation(
            admin, fixture, status="cancel_requested", provider_job_id="prov-cancel",
        )
        worked = await worker.run_one()
        row = await admin.fetchrow(
            "SELECT status, lease_expires_at IS NULL AS released FROM"
            " gpu_provider_invocations WHERE id = $1",
            cancelling,
        )
        report.require(
            "claim:run-one-finishes-a-cancellation",
            worked and row["status"] == "cancelled" and row["released"],
            f"the cancel branch reached status {row['status']} through the same "
            "binding",
        )

        print("\ncanary B - CALLBACK / LEASE-INDEPENDENT", flush=True)

        # ------------------------------------------------------------------
        # CALLBACK. No lease exists, so no lease is bound or invented.
        # ------------------------------------------------------------------
        await _clear_invocations(admin, fixture)
        callback_row = await _seed_invocation(
            admin, fixture, status="running", provider_job_id="prov-proof",
            attempt_count=1,
        )
        await admin.execute(
            "INSERT INTO gpu_provider_attempts (id, tenant_id, invocation_id,"
            " attempt_number, status, request_manifest_sha256, created_at)"
            " VALUES ($1,$2,$3,1,'submitted',$4,now())",
            uuid.uuid4(), fixture.tenant, callback_row, "a" * 64,
        )
        unsent = await _seed_invocation(admin, fixture, status="queued")

        async with sessions() as session:
            no_context = await session.scalar(
                text("SELECT count(*) FROM gpu_provider_invocations WHERE id = :i"),
                {"i": callback_row},
            )
        report.require(
            "callback:the-old-read-by-id-sees-nothing",
            no_context == 0,
            f"admit_callback's previous read named no tenant and returns "
            f"{no_context} rows under a disarmed role - a second canary-B blocker, "
            "separate from _locked_invocation and not caught by Gate 1A",
        )

        async with sessions() as session:
            target = await resolve_callback_target(
                session, function=CALLBACK_RESOLVER, invocation_id=callback_row
            )
        report.require(
            "callback:the-resolver-answers-whose-row-it-is",
            target is not None
            and target.callback_id == callback_row
            and target.tenant_id == fixture.tenant
            and target.project_id == fixture.project,
            f"three identifiers and no lease: {target}",
        )

        async with sessions() as session:
            unknown = await resolve_callback_target(
                session, function=CALLBACK_RESOLVER, invocation_id=uuid.uuid4()
            )
        async with sessions() as session:
            never_sent = await resolve_callback_target(
                session, function=CALLBACK_RESOLVER, invocation_id=unsent
            )
        report.require(
            "callback:the-resolver-declines-what-is-not-a-callback-target",
            unknown is None and never_sent is None,
            "an unknown row and a row the provider was never given both resolve "
            "to nothing, so neither can be used to learn a tenant",
        )

        async with sessions() as session:
            await enter_callback_context(
                session,
                callback=WorkerCallback(
                    callback_id=callback_row, tenant_id=fixture.tenant,
                    project_id=fixture.project,
                ),
            )
            own = await session.scalar(
                text("SELECT count(*) FROM gpu_provider_invocations WHERE id = :i"),
                {"i": callback_row},
            )
            other = await session.scalar(
                text("SELECT count(*) FROM gpu_provider_invocations WHERE id = :i"),
                {"i": unsent},
            )
            settings = {
                name: await _guc(session, name)
                for name in ("app.claim_id", "app.lease_token", "app.callback_id",
                             "app.control_plane")
            }
        report.require(
            "callback:binding-reaches-one-row-and-no-other",
            own == 1 and other == 0,
            "the callback binding admits the row the callback is about and no "
            "other row in the same tenant and project",
        )
        report.require(
            "callback:binding-holds-no-claim-and-no-lease",
            settings["app.claim_id"] is None
            and settings["app.lease_token"] is None
            and settings["app.callback_id"] == str(callback_row)
            and settings["app.control_plane"] is None,
            "the claim and lease settings are cleared rather than filled in - the "
            "invented lease token this path used to carry is gone, not hidden",
        )

        pending_claim = await worker._claim_via_broker()
        assert pending_claim is not None
        result, body = _result_for(pending_claim, {"gpu_seconds": 2.0})
        store.body = body
        await admin.execute(
            "UPDATE gpu_provider_invocations SET lease_expires_at = now() -"
            " interval '1 second', status = 'running' WHERE id = $1",
            callback_row,
        )
        accepted = await worker.admit_callback(
            invocation_id=callback_row,
            provider_event_id="evt-proof",
            provider_event_sha256="f" * 64,
            result=result,
        )
        row = await admin.fetchrow(
            "SELECT status, completion_source, provider_callback_id FROM"
            " gpu_provider_invocations WHERE id = $1",
            callback_row,
        )
        report.require(
            "callback:admit-callback-completes-a-leaseless-row",
            accepted
            and row["status"] == "completed"
            and row["completion_source"] == "callback"
            and row["provider_callback_id"] == "evt-proof",
            f"the real callback path admitted a row carrying no lease: status "
            f"{row['status']}, source {row['completion_source']}",
        )

        replayed = await worker.admit_callback(
            invocation_id=callback_row,
            provider_event_id="evt-proof",
            provider_event_sha256="f" * 64,
            result=result,
        )
        report.require(
            "callback:admission-is-idempotent-under-the-binding",
            replayed,
            "the same callback replayed is admitted again without a second write",
        )

        print("\ncanary B - OTHER, and the gaps", flush=True)

        # ------------------------------------------------------------------
        # OTHER. Observability, which reads counts and no rows.
        # ------------------------------------------------------------------
        await _clear_invocations(admin, fixture)
        for _ in range(2):
            await _seed_invocation(admin, fixture)
        await worker._observe_poll(claimed=False)
        from akc_scheduler.telemetry import CLAIM_POLL_BACKLOG, CLAIM_POLL_CLAIMABLE

        def gauge(metric: Any) -> float:
            return float(metric.labels(queue="gpu_provider_invocations")._value.get())

        report.require(
            "other:the-backlog-probes-still-see-the-queue",
            gauge(CLAIM_POLL_BACKLOG) == 2 and gauge(CLAIM_POLL_CLAIMABLE) == 2,
            f"backlog {gauge(CLAIM_POLL_BACKLOG)}, claimable "
            f"{gauge(CLAIM_POLL_CLAIMABLE)} - the detector that has to tell "
            "starvation from an idle queue is not itself starved",
        )

        # ------------------------------------------------------------------
        # Known gaps, asserted as gaps. Fixing one turns this file red.
        # ------------------------------------------------------------------
        gap_claim = await worker._claim_via_broker()
        assert gap_claim is not None
        insert_state: str | None = None
        try:
            async with sessions() as session, session.begin():
                await enter_claim_context(
                    session,
                    claim=WorkerClaim(
                        claim_id=gap_claim.invocation_id,
                        tenant_id=gap_claim.tenant_id,
                        project_id=gap_claim.project_id,
                        lease_token=gap_claim.lease_token,
                        lease_expires_at=gap_claim.lease_expires_at,
                        claimed_by=CANARY_ROLE,
                    ),
                    worker_id=CANARY_ROLE,
                    now=datetime.now(UTC),
                )
                await session.execute(
                    text(
                        "INSERT INTO gpu_provider_invocations (id, tenant_id, job_id,"
                        " project_id, document_id, document_version_id, provider,"
                        " provider_key, endpoint_id, idempotency_key,"
                        " request_manifest_sha256, status, input_bucket,"
                        " input_object_key, input_sha256, output_object_key, options,"
                        " model_revision, runtime_image_digest, adapter_version,"
                        " transition_policy, transition_attempt, attempt_count,"
                        " cancel_attempt_count, max_attempts, available_at,"
                        " event_sequence, created_at, updated_at) VALUES"
                        " (:id,:t,:j,:p,:d,'v1','runpod','parser','ep-1',:k,:m,"
                        "'queued','source','in/key',:s,'out/key','{}',:r,:g,'ad-1',"
                        "'{}',0,0,0,3,now(),0,now(),now())"
                    ),
                    {"id": uuid.uuid4(), "t": fixture.tenant, "j": fixture.job,
                     "p": fixture.project, "d": fixture.document, "k": "idem-gap",
                     "m": "a" * 64, "s": "b" * 64, "r": "d" * 48,
                     "g": "sha256:" + "c" * 64},
                )
        except DBAPIError as error:
            insert_state = str(getattr(error.orig, "sqlstate", ""))
        report.require(
            "gap:transition-child-insert-is-denied",
            insert_state == "42501",
            f"_create_transition cannot write its child row ({insert_state}): "
            f"{CANARY_ROLE} holds no INSERT on gpu_provider_invocations. This "
            "fails identically with BYPASSRLS on, so it is a pre-existing gap "
            "rather than one canary B introduces - see "
            "docs/audit/V5_GPU_ACCESS_SITE_MATRIX.md",
        )

        parent = await _seed_invocation(admin, fixture, status="failed")
        async with sessions() as session:
            await enter_claim_context(
                session,
                claim=WorkerClaim(
                    claim_id=gap_claim.invocation_id, tenant_id=gap_claim.tenant_id,
                    project_id=gap_claim.project_id,
                    lease_token=gap_claim.lease_token,
                    lease_expires_at=gap_claim.lease_expires_at,
                    claimed_by=CANARY_ROLE,
                ),
                worker_id=CANARY_ROLE,
                now=datetime.now(UTC),
            )
            visible = await session.scalar(
                text("SELECT count(*) FROM gpu_provider_invocations WHERE id = :i"),
                {"i": parent},
            )
        report.require(
            "gap:lineage-parent-row-is-unreadable",
            visible == 0,
            "_lineage_state walks parent_invocation_id, and the claim binding "
            "admits one row - so a transitioned invocation's failure path raises "
            "gpu_invocation_lineage_parent_missing. Unreachable while the child "
            "INSERT above is denied, and recorded so it cannot be forgotten if "
            "that is ever granted",
        )
    finally:
        if engine is not None:
            await engine.dispose()
        try:
            if provisioned:
                await admin.execute(f"REVOKE {CANARY_ROLE} FROM {PROOF_LOGIN}")
                # Dropped, not merely de-credentialed. A role left behind is a
                # role in the catalog, and the catalog is what the privilege
                # receipt hashes — the first version of this cleanup only
                # cleared the password and the committed receipt drifted.
                await admin.execute(f"DROP ROLE IF EXISTS {PROOF_LOGIN}")
            for table in ("audit_events", "gpu_invocation_events",
                          "gpu_provider_attempts", "outbox_events", "job_events",
                          "gpu_provider_invocations", "processing_jobs", "documents",
                          "projects"):
                await admin.execute(
                    f"DELETE FROM {table} WHERE tenant_id = ANY("  # noqa: S608
                    " SELECT id FROM tenants WHERE slug LIKE 'canary-b-%')"
                )
            await admin.execute("DELETE FROM tenants WHERE slug LIKE 'canary-b-%'")
            await admin.execute(
                "DELETE FROM users WHERE email LIKE '%@canary.invalid'"
            )
        finally:
            await admin.close()
    return report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    report = asyncio.run(run(_admin_url()))
    print(f"\ncanary B proof passed: {len(report.passed)} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
