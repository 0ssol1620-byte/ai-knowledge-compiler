"""Exercise role grants emitted by the append-only ledger migration."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace


def _grant_api_plane(op: SimpleNamespace) -> None:
    # Extract the production function so this SQL emission test needs neither
    # a database server nor imports used only by table construction.
    path = Path(__file__).resolve().parents[2] / "migrations/versions/0038_identity_ledger.py"
    source = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node
        for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name == "_grant_api_plane"
    )
    module = ast.Module(body=[function], type_ignores=[])
    namespace = {"op": op, "_TABLE": "identity_ledger", "_API_PLANE_ROLE": "akc_api_plane"}
    exec(compile(module, str(path), "exec"), namespace)  # noqa: S102 - fixed repository AST only.
    namespace["_grant_api_plane"]()


def test_postgresql_grant_uses_resolved_fixed_identifiers() -> None:
    statements: list[str] = []
    _grant_api_plane(
        SimpleNamespace(
            get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
            execute=statements.append,
        ),
    )

    assert len(statements) == 1
    sql = statements[0]
    assert "IF EXISTS" in sql
    assert "rolname = 'akc_api_plane'" in sql
    assert 'GRANT SELECT, INSERT ON TABLE "identity_ledger" TO "akc_api_plane";' in sql
    assert "{_TABLE}" not in sql
    assert "EXECUTE" not in sql
    assert "UPDATE" not in sql and "DELETE" not in sql


def test_non_postgresql_grant_does_not_emit_sql() -> None:
    statements: list[str] = []
    _grant_api_plane(
        SimpleNamespace(
            get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
            execute=statements.append,
        ),
    )

    assert statements == []
