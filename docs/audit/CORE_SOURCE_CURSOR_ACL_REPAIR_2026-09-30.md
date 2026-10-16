# Hosted source-cursor ACL failure repair — 2026-09-30

The actual hosted PostgreSQL log, job 109950216644, shows migration **0040** ran
after 0039. The failure summary's through-0039 shorthand omitted this final step.
0040 grants SELECT, INSERT and table-wide UPDATE on source_cursors to
akc_scheduler. Those three grants violate the existing approved scheduler table
surface and correctly trigger effective_table_acl_exact. Current code contains
an API freshness reader but no scheduler cursor writer. Expanding the capability
allowlist would authorize unused writes and is not the repair.

Forward migration 0041 removes unused scheduler table privileges. Neither the
scheduler capability query nor its least-privilege allowlist is changed. Earlier
migrations remain intact, so an already-upgraded database receives the repair.
Explicit downgrade restores 0040's previous grant shape, including its known
capability mismatch; that rollback is not asserted as a safe running release.

0040 also installed only RESTRICTIVE tenant policies, which cannot admit reads
alone. The forward migration adds a SELECT-only permissive policy for the
already-granted API plane, explicitly bound to app.tenant_id, retaining existing
forced RLS and restrictive tenancy. It grants no API writes or scheduler reads.

## Real PostgreSQL evidence

An isolated PostgreSQL 17.2 cluster on 127.0.0.1:55473 ran the real 0001–0023
migrations into a fresh synthetic acl_qualification database. The committed
contract test applies actual 0039, 0040 and 0041 in one rolled-back transaction:

- Exact scheduler table ACL passes before cursor migration, fails after 0040,
  and passes after 0041, including repeated upgrade.
- Scheduler cursor SELECT/INSERT/UPDATE/DELETE privileges are all absent.
- API reads expose only the selected tenant; another tenant and unset context
  cannot expose those rows. UPDATE/DELETE/INSERT are rejected by PostgreSQL.
- A deliberately excessive scheduler table UPDATE still fails the unchanged
  guard, proving the repair has not bypassed it.
- Transaction rollback removes rehearsal objects/grants and synthetic data.

This is actual privilege and RLS qualification, not a mocked green capability.
Full chain rehearsal remains blocked locally at missing pgvector; later cursor
migrations are tested independently against their real required schema. Hosted
full-head verification is still required. The disposable server is stopped after
qualification; existing user services and machine settings remain untouched.

Reproduction requires an explicit loopback database whose name ends in
_qualification and a baseline through 0023, with no source_cursors table:

```powershell
$env:AKC_CURSOR_REHEARSAL_DATABASE_URL = 'postgresql+asyncpg://postgres@127.0.0.1:55473/acl_qualification'
# Set PYTHONPATH to this worktree's packages/*/src and services/*/src.
..\core-work\.venv\Scripts\python.exe -m pytest tests/unit/test_source_cursor_plane_migration.py tests/contract/test_source_cursor_plane_postgres.py -q --basetemp ..\pytest-acl-repeat
```

Three focused tests passed, including the real PostgreSQL contract test. The
optional infrastructure test skips when no explicit rehearsal URL is supplied;
the passing result above supplied it and executed every assertion.
The complete bounded scheduler suite passed 150 tests; source adapter/migration
coverage passed 20 tests. Ruff, formatting and whitespace checks passed. The
single Alembic head is now 0041_source_cursor_acl, within the version column's
32-character bound. No previous guard assertion or security test was removed.

Checkout: task-3/core-acl, codex/core-acl-repair, based on
36f8f99bf298c4177bb9c7808920eda81d7c6632. Prior checkouts remain unchanged.

Main's evidence confirms the hosted API image build/Trivy/SBOM gate passed on its
recorded PR merge checkout. Scheduler/web/CPU image and Linux visual jobs had no
runner allocation and remain unqualified. This lane performs no hosted rerun,
visibility transition, publication, credential, billing or security setting change.
