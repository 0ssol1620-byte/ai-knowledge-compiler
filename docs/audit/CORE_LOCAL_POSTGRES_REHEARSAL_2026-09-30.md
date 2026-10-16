# Local PostgreSQL rehearsal — 2026-09-30

Installed PostgreSQL 17.2 binaries were available outside PATH. Qualification used
a new disposable cluster under task-3/postgres-qualification, bound only to
127.0.0.1:55473. Existing services were untouched. Only synthetic data and the
built-in local postgres role plus a NOLOGIN akc_api_plane role were used.

The real Alembic chain passed 0001 through 0023, then stopped at 0024 because
the installed server has no vector.control extension. No migration was skipped
or substituted. Server headers and import libraries exist, but cl/nmake and
Visual Studio Build Tools are absent, so a local pgvector build is also blocked.
No software, credentials or machine security settings were added.

The real 0038 migration independently passed upgrade twice and downgrade on this
PostgreSQL server. Assertions verified exactly SELECT/INSERT grants, enabled and
forced RLS, SELECT/INSERT policies, and table removal on downgrade. This qualifies
the repaired GRANT SQL; it does not qualify the complete migration chain.
The disposable server was stopped and pg_isready confirmed no response.
The reproduction script is task-3/postgres-ledger-probe.py outside Git.

Docker and Podman commands and usual installation paths are absent. WSL distro
enumeration returned Wsl/EnumerateDistros/Service E_ACCESSDENIED. Image builds,
runtime probes and rebuilt image scans therefore remain blocked locally. Existing
filesystem scans and registry/package inspection are separate evidence and do
not establish rebuilt-image acceptance. No elevation or service changes were made.
