"""Canary B rollback — re-arm the GPU worker, immediately, without alembic.

Prepared before canary B runs, not after. A rollback written during an incident
is a rollback nobody has tested.

``alembic downgrade 0036_claim_backlog_probe`` does the same thing and is the
ordinary path. This exists for the case where alembic is not what you want to be
reaching for: it needs no migration state, no revision history and no consistent
head, it touches exactly one role attribute, and it says what it did.

    AKC_CI_ADMIN_DATABASE_URL=postgresql://... python \\
        infra/postgres/canary_b_rollback.py

Exit code 0 means the GPU worker holds ``BYPASSRLS`` again — which is also the
exit code when it already did, because a rollback that fails when there is
nothing to roll back is a rollback people hesitate to run.

**It re-arms one role.** If canary B is red, the instruction is to restore the
GPU worker and stop; expanding to another worker is forbidden until canary B is
green, and this script cannot do it.
"""

from __future__ import annotations

import asyncio
import os
import sys
from urllib.parse import urlsplit

import asyncpg  # type: ignore[import-untyped]

CANARY_ROLE = "akc_gpu_worker"
EXPECTED_ARMED = 7


def _url() -> str:
    value = os.environ.get("AKC_CI_ADMIN_DATABASE_URL", "")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"postgresql", "postgres"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or not parsed.path.strip("/")
    ):
        raise RuntimeError("rollback requires an explicit loopback URL")
    return value


async def rollback(url: str) -> int:
    connection = await asyncpg.connect(url)
    try:
        before = await connection.fetchval(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname = $1", CANARY_ROLE
        )
        if before is None:
            print(f"{CANARY_ROLE} does not exist; nothing to roll back", file=sys.stderr)
            return 2
        if before:
            print(f"{CANARY_ROLE} already holds BYPASSRLS; nothing to do")
        else:
            await connection.execute(f"ALTER ROLE {CANARY_ROLE} BYPASSRLS")
            print(f"{CANARY_ROLE} re-armed")

        armed = await connection.fetch(
            "SELECT rolname FROM pg_roles "
            "WHERE rolname LIKE 'akc\\_%' ESCAPE '\\' AND rolbypassrls "
            "ORDER BY rolname"
        )
        names = [str(row["rolname"]) for row in armed]
        if CANARY_ROLE not in names:
            print(f"{CANARY_ROLE} did not regain BYPASSRLS", file=sys.stderr)
            return 1
        print(f"BYPASSRLS holders: {len(names)}/{EXPECTED_ARMED} -> {', '.join(names)}")
        if len(names) != EXPECTED_ARMED:
            # Not a failure of this rollback — it did its one job — but the
            # cluster is not in the shape anything else assumes, and saying so
            # is more use than a silent success.
            print(
                f"WARNING: {EXPECTED_ARMED - len(names)} other worker role(s) are "
                "disarmed. Canary B is the GPU worker alone; investigate before "
                "expanding anything.",
                file=sys.stderr,
            )
        return 0
    finally:
        await connection.close()


def main() -> int:
    return asyncio.run(rollback(_url()))


if __name__ == "__main__":
    raise SystemExit(main())
