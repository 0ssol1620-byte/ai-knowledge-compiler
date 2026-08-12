"""Canary B, as an operation somebody performs — not as a migration.

``0037`` used to read ``AKC_CANARY_B_DISARM_GPU`` and remove ``BYPASSRLS`` from
``akc_gpu_worker`` when it was set. That made one Alembic revision describe two
different privilege states, and worse, a run that no-opped left the revision
marked applied — so setting the variable later did nothing at all, because
Alembic does not re-run a revision it has already recorded. A migration says what
the database *is*. Removing an attribute from one role in one environment while
you watch it is not that; it is a thing an operator does, once, deliberately, and
undoes if it goes badly.

    AKC_CI_ADMIN_DATABASE_URL=postgresql://... python \\
        infra/postgres/canary_b_disarm.py --confirm akc_gpu_worker

**Rehearsal is the default.** Without ``--leave-disarmed`` the attribute is
restored before this exits, whatever the proof said, and what you get is a full
dress run: the disarm, the blast-radius assertion, the complete proof against a
genuinely disarmed role, the receipt, and the rollback. That is the mode CI and
any developer should ever need. ``--leave-disarmed`` is canary B itself and
leaves the cluster changed; it is for one staging cluster and a person watching
it.

**Four things happen in order, and a failure at any of them re-arms.**

1. The pre-state is asserted at seven armed worker roles. A cluster that is
   already part-way through something is not a cluster to start a canary on.
2. ``akc_gpu_worker`` alone loses ``BYPASSRLS``, and the blast radius is measured
   rather than assumed: exactly six remain and this role is not among them.
3. ``infra/postgres/verify_gpu_nobypassrls.py`` runs. It refuses to run against
   an armed role, so it cannot pass by having measured nothing.
4. A receipt is written naming what was flipped, what the catalog then looked
   like, and every proof case that passed.

Rollback is ``infra/postgres/canary_b_rollback.py``, imported and called rather
than reimplemented — the rollback that runs on a bad canary is then the same code
path that was rehearsed, instead of a second one written beside it.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import asyncpg  # type: ignore[import-untyped]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from infra.postgres.canary_b_rollback import rollback
from infra.postgres.verify_gpu_nobypassrls import run as run_proof
from scripts.generate_privilege_receipt import collect, findings

CANARY_ROLE = "akc_gpu_worker"
EXPECTED_ARMED_BEFORE = 7
EXPECTED_ARMED_AFTER = 6
RECEIPT_SCHEMA = "tavonel.canary-b-receipt.v1"
DEFAULT_RECEIPT = Path("docs/audit/receipts/canary-b-gpu-worker.json")

_ARMED = (
    r"SELECT rolname FROM pg_roles WHERE rolname LIKE 'akc\_%' ESCAPE '\'"
    " AND rolbypassrls ORDER BY rolname"
)


class CanaryRefused(RuntimeError):
    """The cluster or the invocation is not one this may act on."""


def _url() -> str:
    value = os.environ.get("AKC_CI_ADMIN_DATABASE_URL", "")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"postgresql", "postgres"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or not parsed.path.strip("/")
    ):
        raise CanaryRefused("canary B requires an explicit loopback URL")
    return value


async def _armed(connection: asyncpg.Connection) -> list[str]:
    return [str(row["rolname"]) for row in await connection.fetch(_ARMED)]


def _hashed(receipt: dict[str, Any]) -> str:
    body = json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    """Same rendering as the privilege receipt: sorted keys, two-space indent."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


async def canary(url: str, *, leave_disarmed: bool, receipt_path: Path) -> int:
    admin = await asyncpg.connect(url)
    disarmed_at: str | None = None
    restored = False
    try:
        before = await _armed(admin)
        if CANARY_ROLE not in before:
            raise CanaryRefused(
                f"{CANARY_ROLE} does not hold BYPASSRLS. Either canary B is "
                "already running or this cluster is in a state nobody described; "
                "either way this is not where it starts."
            )
        if len(before) != EXPECTED_ARMED_BEFORE:
            raise CanaryRefused(
                f"expected {EXPECTED_ARMED_BEFORE} armed worker roles before "
                f"canary B, found {len(before)}: {before}"
            )
        print(f"before: {len(before)}/{EXPECTED_ARMED_BEFORE} armed -> "
              f"{', '.join(before)}")

        await admin.execute(f"ALTER ROLE {CANARY_ROLE} NOBYPASSRLS")
        disarmed_at = datetime.now(UTC).isoformat()
        after = await _armed(admin)
        if CANARY_ROLE in after:
            raise CanaryRefused(f"{CANARY_ROLE} still holds BYPASSRLS after the ALTER")
        if len(after) != EXPECTED_ARMED_AFTER:
            raise CanaryRefused(
                f"expected {EXPECTED_ARMED_AFTER} armed worker roles after the "
                f"disarm, found {len(after)}: {after}"
            )
        print(f"disarmed {CANARY_ROLE}: {len(after)}/{EXPECTED_ARMED_BEFORE} still "
              f"armed -> {', '.join(after)}")

        catalog = await collect(admin)
        catalog["findings"] = findings(catalog)
        catalog_hash = _hashed(catalog)

        report = await run_proof(url)

        receipt: dict[str, Any] = {
            "schema": RECEIPT_SCHEMA,
            "canary": "B",
            "role": CANARY_ROLE,
            "alembic_revision": catalog["alembic_revision"],
            "disarmed_at": disarmed_at,
            "armed_before": before,
            "armed_while_disarmed": after,
            "mode": "canary" if leave_disarmed else "rehearsal",
            "proof": "infra/postgres/verify_gpu_nobypassrls.py",
            "proof_cases": sorted(report.passed),
            "proof_case_count": len(report.passed),
            # The catalog as it stood while the role was disarmed, by hash. The
            # full receipt is 112 tables; what changed is the role section, and
            # it is quoted in full above.
            "privilege_receipt_sha256": catalog_hash,
            "roles": [
                dict(role)
                for role in catalog["roles"]
                if str(role["rolname"]).startswith("akc_")
            ],
        }
        receipt["receipt_sha256"] = _hashed(receipt)
        await asyncio.to_thread(_write_receipt, receipt_path, receipt)
        print(f"\nwrote {receipt_path}: {len(report.passed)} proof cases, "
              f"receipt_sha256 {receipt['receipt_sha256']}")

        if leave_disarmed:
            print(
                f"\n{CANARY_ROLE} is left NOBYPASSRLS. Canary B is now running: "
                "watch the claim-poll series and hold one full retention cycle. "
                "infra/postgres/canary_b_rollback.py re-arms it."
            )
            return 0
        restored = await rollback(url) == 0
        return 0 if restored else 1
    except Exception as error:
        # Every exception, not only the three this file defines. A rehearsal
        # that raised an IntegrityError from inside the proof left the role
        # disarmed once, because the handler named the tidy failures and not the
        # untidy ones — and an untidy failure is exactly when a cluster should
        # not be left changed.
        print(f"\ncanary B FAILED: {type(error).__name__}: {error}", file=sys.stderr)
        if disarmed_at is not None:
            print("re-arming through the prepared rollback path", file=sys.stderr)
            restored = await rollback(url) == 0
            if not restored:
                print(
                    "ROLLBACK DID NOT RESTORE THE ROLE. Run "
                    "infra/postgres/canary_b_rollback.py by hand.",
                    file=sys.stderr,
                )
                return 2
        return 1
    finally:
        await admin.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm",
        required=True,
        help=f"must be exactly {CANARY_ROLE}; canary B is one role and this is "
             "where that is enforced against a typo",
    )
    parser.add_argument(
        "--leave-disarmed",
        action="store_true",
        help="perform canary B rather than rehearse it: do not restore the "
             "attribute before exiting",
    )
    parser.add_argument("--receipt-out", type=Path, default=DEFAULT_RECEIPT)
    arguments = parser.parse_args()
    if arguments.confirm != CANARY_ROLE:
        print(
            f"--confirm must be {CANARY_ROLE}, not {arguments.confirm!r}",
            file=sys.stderr,
        )
        return 2
    return asyncio.run(
        canary(
            _url(),
            leave_disarmed=arguments.leave_disarmed,
            receipt_path=arguments.receipt_out,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
