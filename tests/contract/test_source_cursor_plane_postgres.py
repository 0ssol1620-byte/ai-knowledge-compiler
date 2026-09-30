"""Real catalog and RLS rehearsal on an explicitly disposable PostgreSQL database."""

import importlib.util
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from akc_scheduler.database import _POSTGRES_CAPABILITY_QUERY
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine


def _upgrade(connection, filename):
    path = Path(__file__).parents[2] / "migrations/versions" / filename
    spec = importlib.util.spec_from_file_location(filename, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        module.upgrade()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cursor_acl_repair_and_tenant_read_isolation():
    url = os.environ.get("AKC_CURSOR_REHEARSAL_DATABASE_URL", "")
    if not url:
        pytest.skip("explicit disposable PostgreSQL rehearsal URL required")
    parsed = urlsplit(url)
    assert parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    assert parsed.path.endswith("_qualification")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                assert await connection.scalar(text("SELECT to_regclass('source_cursors')")) is None
                await connection.execute(
                    text("""
                    DO $$ BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'akc_api_plane') THEN
                            CREATE ROLE akc_api_plane NOLOGIN NOINHERIT NOBYPASSRLS;
                        END IF;
                    END $$;
                    """)
                )
                await connection.execute(text("GRANT USAGE ON SCHEMA public TO akc_api_plane"))
                for filename in ("0039_source_adapter_cursors.py", "0040_source_cursor_tenancy.py"):
                    await connection.run_sync(_upgrade, filename)
                await connection.execute(text("SET LOCAL ROLE akc_scheduler"))
                before = (await connection.execute(_POSTGRES_CAPABILITY_QUERY)).mappings().one()
                assert before["effective_table_acl_exact"] is False
                await connection.execute(text("RESET ROLE"))
                for _ in range(2):
                    await connection.run_sync(_upgrade, "0041_source_cursor_plane_privileges.py")
                await connection.execute(text("SET LOCAL ROLE akc_scheduler"))
                after = (await connection.execute(_POSTGRES_CAPABILITY_QUERY)).mappings().one()
                assert after["effective_table_acl_exact"] is True
                assert after["effective_column_acl_exact"] is True
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert not await connection.scalar(
                        text(
                            "SELECT has_table_privilege(current_user, 'source_cursors', :privilege)"
                        ),
                        {"privilege": privilege},
                    )
                await connection.execute(text("RESET ROLE"))
                await connection.execute(
                    text("""
                    INSERT INTO source_cursors(source_id, adapter, cursor, tenant_id) VALUES
                    ('one', 'synthetic', '{}', '11111111-1111-1111-1111-111111111111'),
                    ('two', 'synthetic', '{}', '22222222-2222-2222-2222-222222222222')
                    """)
                )
                await connection.execute(text("SET LOCAL ROLE akc_api_plane"))
                for tenant, expected in (
                    ("11111111-1111-1111-1111-111111111111", "one"),
                    ("22222222-2222-2222-2222-222222222222", "two"),
                ):
                    await connection.execute(
                        text("SELECT set_config('app.tenant_id', :tenant, true)"),
                        {"tenant": tenant},
                    )
                    assert (
                        await connection.execute(text("SELECT source_id FROM source_cursors"))
                    ).scalars().all() == [expected]
                await connection.execute(text("SELECT set_config('app.tenant_id', '', true)"))
                assert (
                    await connection.execute(text("SELECT source_id FROM source_cursors"))
                ).scalars().all() == []
                for statement in (
                    "UPDATE source_cursors SET cursor = '{}'",
                    "DELETE FROM source_cursors",
                    "INSERT INTO source_cursors(source_id, adapter, cursor, tenant_id) "
                    "VALUES ('x', 'synthetic', '{}', '11111111-1111-1111-1111-111111111111')",
                ):
                    savepoint = await connection.begin_nested()
                    with pytest.raises(DBAPIError, match="permission denied"):
                        await connection.execute(text(statement))
                    await savepoint.rollback()
                await connection.execute(text("RESET ROLE"))
                await connection.execute(text("GRANT UPDATE ON outbox_events TO akc_scheduler"))
                await connection.execute(text("SET LOCAL ROLE akc_scheduler"))
                excessive = (await connection.execute(_POSTGRES_CAPABILITY_QUERY)).mappings().one()
                assert excessive["effective_table_acl_exact"] is False
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
