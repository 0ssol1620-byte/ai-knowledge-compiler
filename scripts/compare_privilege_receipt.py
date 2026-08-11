"""Compare two privilege receipts over the portion the schema determines.

``generate_privilege_receipt.py --check`` compares files byte for byte, which is
the right gate when both receipts come from the same cluster. Across clusters it
reports drift that is not drift: the receipt records the table owner and every
non-``pg_`` role, so a receipt taken on a cluster whose bootstrap superuser is
``pgowner`` can never equal one taken on CI, where it is ``postgres``. That
difference says nothing about whether the schema is still safe.

This compares what the migrations decide and ignores what the cluster decides:

* per table — tenant/workspace/project columns, RLS enabled, RLS forced, policy
  count, and each policy's kind, command, roles and expressions;
* per table — grants, with the owner's own row dropped, since owner rights come
  with ownership and the owner's *name* is cluster provenance;
* the ``akc_`` roles and their attributes, which the migrations create;
* the alembic revision and the findings list.

Policy expressions are compared after replacing the owner's name, so an
identical policy does not read as changed merely because it was created by a
differently named owner.

    python scripts/compare_privilege_receipt.py <expected.json> <actual.json>

Exits non-zero and prints every difference when the schema-determined portion
disagrees.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_POLICY_FIELDS = ("name", "command", "kind", "roles", "using", "with_check")


def _normalise_owner(value: Any, owner: str) -> Any:
    if isinstance(value, str) and owner:
        return value.replace(owner, "<owner>")
    return value


def comparable(receipt: dict[str, Any]) -> dict[str, Any]:
    """Strip the receipt down to what the migration tree determines."""

    tables: dict[str, Any] = {}
    for table in receipt["tables"]:
        owner = str(table["owner"])
        tables[str(table["table"])] = {
            "tenant_id": table["tenant_id"],
            "workspace_id": table["workspace_id"],
            "project_id": table["project_id"],
            "rls_enabled": table["rls_enabled"],
            "rls_forced": table["rls_forced"],
            "policy_count": table["policy_count"],
            "append_only": table["append_only"],
            "global_control": table["global_control"],
            "policies": sorted(
                (
                    {
                        field: _normalise_owner(policy.get(field), owner)
                        for field in _POLICY_FIELDS
                    }
                    for policy in table["policies"]
                ),
                key=lambda policy: str(policy["name"]),
            ),
            # The owner holds every privilege by definition and its name is
            # cluster provenance, so only the granted roles are comparable.
            "grants": {
                grantee: sorted(privileges)
                for grantee, privileges in table["grants"].items()
                if grantee != owner
            },
        }
    roles = {
        str(role["rolname"]): {
            key: value for key, value in role.items() if key != "rolname"
        }
        for role in receipt["roles"]
        if str(role["rolname"]).startswith("akc_")
    }
    return {
        "alembic_revision": receipt["alembic_revision"],
        "table_count": receipt["table_count"],
        "tables": tables,
        "roles": roles,
        "findings": sorted(
            (json.dumps(finding, sort_keys=True) for finding in receipt.get("findings", [])),
        ),
    }


def differences(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if expected["alembic_revision"] != actual["alembic_revision"]:
        out.append(
            f"alembic revision: {expected['alembic_revision']} != {actual['alembic_revision']}"
        )
    missing = sorted(set(expected["tables"]) - set(actual["tables"]))
    added = sorted(set(actual["tables"]) - set(expected["tables"]))
    for name in missing:
        out.append(f"table missing from actual: {name}")
    for name in added:
        out.append(f"table absent from expected: {name}")
    for name in sorted(set(expected["tables"]) & set(actual["tables"])):
        left, right = expected["tables"][name], actual["tables"][name]
        for field in sorted(left):
            if left[field] != right[field]:
                out.append(f"{name}.{field}: {left[field]!r} != {right[field]!r}")
    # Roles the migrations create must match exactly. A deployment may add login
    # roles on top (infra/postgres/init/010-scheduler-runtime.sql creates the
    # akc_*_runtime logins that CI uses and the receipt's origin cluster did
    # not), so an extra role is tolerated only while it is unprivileged — a new
    # BYPASSRLS or SUPERUSER role is exactly what this must never wave through.
    for name in sorted(set(expected["roles"]) & set(actual["roles"])):
        if expected["roles"][name] != actual["roles"][name]:
            out.append(f"role {name}: {expected['roles'][name]!r} != {actual['roles'][name]!r}")
    for name in sorted(set(expected["roles"]) - set(actual["roles"])):
        out.append(f"role missing from actual: {name}")
    for name in sorted(set(actual["roles"]) - set(expected["roles"])):
        attributes = actual["roles"][name]
        if attributes.get("rolbypassrls") or attributes.get("rolsuper"):
            out.append(f"unexpected privileged role in actual: {name} {attributes!r}")
    if expected["findings"] != actual["findings"]:
        for finding in sorted(set(actual["findings"]) - set(expected["findings"])):
            out.append(f"new finding: {finding}")
        for finding in sorted(set(expected["findings"]) - set(actual["findings"])):
            out.append(f"resolved finding (update the committed receipt): {finding}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected", type=Path)
    parser.add_argument("actual", type=Path)
    args = parser.parse_args()

    expected = comparable(json.loads(args.expected.read_text(encoding="utf-8")))
    actual = comparable(json.loads(args.actual.read_text(encoding="utf-8")))
    found = differences(expected, actual)
    if found:
        print(f"privilege receipt drifted ({len(found)} difference(s)):", file=sys.stderr)
        for line in found:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(
        f"privilege receipts agree over {actual['table_count']} tables "
        f"at {actual['alembic_revision']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
