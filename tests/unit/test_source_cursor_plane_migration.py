"""Forward cursor repair keeps the scheduler capability boundary unchanged."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _migration():
    path = Path(__file__).parents[2] / "migrations/versions/0041_source_cursor_plane_privileges.py"
    spec = importlib.util.spec_from_file_location("cursor_plane_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cursor_upgrade_revokes_unused_scheduler_authority_and_scopes_api_read(monkeypatch):
    migration = _migration()
    assert len(migration.revision) <= 32
    statements = []
    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
    )
    monkeypatch.setattr(migration.op, "execute", statements.append)
    migration.upgrade()
    sql = "\n".join(statements)
    assert "REVOKE ALL PRIVILEGES ON TABLE source_cursors FROM akc_scheduler" in sql
    assert "GRANT" not in sql
    assert "AS PERMISSIVE FOR SELECT TO akc_api_plane" in sql
    assert "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid" in sql


def test_cursor_repair_is_postgres_only(monkeypatch):
    migration = _migration()
    statements = []
    monkeypatch.setattr(
        migration.op, "get_bind", lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    )
    monkeypatch.setattr(migration.op, "execute", statements.append)
    migration.upgrade()
    migration.downgrade()
    assert statements == []
