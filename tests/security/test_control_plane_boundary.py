"""The Control Plane Authorization Boundary is stated in three places.

The registry names the approved tables, the security package names the purposes
a transaction may declare, and migration 0034 writes both into SQL policies.
Three copies of one decision drift, and the drift is silent: a purpose added to
the application but not to the policies produces a worker that thinks it has
cross-tenant reach and reads zero rows.

The catalog half — the registry against a live PostgreSQL — is asserted by
``infra/postgres/schema_security_gate.py``. This is the half that needs no
database.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

from akc_security.tenant_context import CONTROL_PLANE_PURPOSES

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations/versions/0034_dual_plane_authorization.py"
REGISTRY = ROOT / "infra/postgres/control_plane_registry.py"


def _registry() -> ModuleType:
    """Load the registry by path; ``infra`` is not an importable package."""

    spec = importlib.util.spec_from_file_location("control_plane_registry", REGISTRY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migration_constant(name: str) -> list[str]:
    source = MIGRATION.read_text(encoding="utf-8")
    match = re.search(rf"^{name} = \(([^)]*)\)", source, re.MULTILINE)
    assert match is not None, f"{name} not found in {MIGRATION.name}"
    return re.findall(r'"([^"]+)"', match.group(1))


def test_the_three_purpose_lists_agree() -> None:
    registry = _registry()
    assert set(CONTROL_PLANE_PURPOSES) == set(registry.CONTROL_PLANE_PURPOSES)
    assert set(CONTROL_PLANE_PURPOSES) == set(_migration_constant("CONTROL_PLANE_PURPOSES"))


def test_the_role_names_agree() -> None:
    registry = _registry()
    source = MIGRATION.read_text(encoding="utf-8")
    for constant in (
        "CONTROL_PLANE_ROLE",
        "HUMAN_PLANE_ROLE",
        "HUMAN_PLANE_LOGIN_ROLE",
    ):
        expected = getattr(registry, constant)
        assert f'{constant} = "{expected}"' in source, f"{constant} disagrees"


def test_every_approved_table_carries_a_reason() -> None:
    """A boundary entry with no reason is a list, not a boundary."""

    registry = _registry()
    tables: dict[str, str] = registry.CONTROL_PLANE_TABLES
    activities = ("discovery", "claim", "lease", "retention", "poll", "fan-out")
    assert tables, "the boundary cannot be empty"
    for table, reason in tables.items():
        assert len(reason) > 30, f"{table} has no usable reason"
        assert any(word in reason for word in activities), (
            f"{table}'s reason names no control-plane activity: {reason!r}"
        )


def test_the_sensitive_column_record_covers_every_approved_table() -> None:
    """Each table in the boundary was examined, and the result was written down.

    A table admitted without its column examination is the failure the founder's
    condition exists to prevent: the boundary would say "control-plane metadata"
    on the strength of a table name.
    """

    registry = _registry()
    tables: dict[str, str] = registry.CONTROL_PLANE_TABLES
    sensitive: dict[str, tuple[str, ...]] = registry.CONTROL_PLANE_SENSITIVE_COLUMNS
    assert set(sensitive) == set(tables)


def test_the_lease_tables_are_the_ones_the_migration_expects() -> None:
    registry = _registry()
    source = MIGRATION.read_text(encoding="utf-8")
    lease_tables: frozenset[str] = registry.LEASE_TABLES
    assert f"EXPECTED_LEASE_TABLES = {len(lease_tables)}" in source
