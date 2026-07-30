"""Restricted database boundary for the isolated URL-fetch worker."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from akc_url_fetcher.settings import UrlFetcherSettings


class UrlFetcherDatabasePrivilegeError(RuntimeError):
    """The runtime login does not match the reviewed least-privilege role."""


@dataclass(frozen=True, slots=True)
class UrlFetcherDatabaseCapability:
    backend: str
    effective_role: str | None
    login_role: str | None
    bypass_rls: bool
    sqlite_test_adapter: bool


_POSTGRES_CAPABILITY_QUERY = text(
    """
    SELECT
        current_user AS effective_role,
        session_user AS login_role,
        COALESCE(role.rolbypassrls, false) AS bypass_rls,
        COALESCE(role.rolcanlogin, true) AS can_login,
        NOT (
            role.rolsuper OR role.rolcreaterole OR role.rolcreatedb
            OR role.rolreplication OR role.rolinherit
        ) AS effective_role_safe,
        (
            login.rolcanlogin
            AND NOT login.rolsuper
            AND NOT login.rolcreaterole
            AND NOT login.rolcreatedb
            AND NOT login.rolreplication
            AND NOT login.rolbypassrls
            AND NOT login.rolinherit
        ) AS login_role_safe,
        (
            pg_has_role(login.oid, role.oid, 'MEMBER')
            AND NOT EXISTS (
                SELECT 1
                FROM pg_auth_members AS membership
                WHERE membership.member = login.oid
                  AND (
                      membership.roleid <> role.oid
                      OR membership.admin_option
                  )
            )
        ) AS login_has_only_effective_role,
        NOT EXISTS (
            SELECT 1
            FROM pg_class AS direct_class
            CROSS JOIN LATERAL aclexplode(direct_class.relacl) AS direct_acl
            WHERE direct_class.relnamespace = 'public'::regnamespace
              AND direct_class.relkind IN ('r', 'p')
              AND direct_class.relname <> 'alembic_version'
              AND direct_acl.grantee = login.oid
        ) AS login_has_no_direct_table_acl,
        NOT EXISTS (
            SELECT 1
            FROM pg_class AS public_class
            CROSS JOIN LATERAL aclexplode(public_class.relacl) AS public_acl
            WHERE public_class.relnamespace = 'public'::regnamespace
              AND public_class.relkind IN ('r', 'p')
              AND public_class.relname <> 'alembic_version'
              AND public_acl.grantee = 0
        ) AS application_tables_have_no_public_acl,
        NOT EXISTS (
            SELECT 1
            FROM pg_class AS owned_class
            WHERE owned_class.relnamespace = 'public'::regnamespace
              AND owned_class.relkind IN ('r', 'p')
              AND owned_class.relname <> 'alembic_version'
              AND owned_class.relowner IN (role.oid, login.oid)
        ) AS worker_owns_no_application_table,
        NOT has_schema_privilege(session_user, 'public', 'CREATE')
            AS login_cannot_create_in_public,
        has_schema_privilege(current_user, 'public', 'USAGE') AS schema_usage,
        (
            has_table_privilege(current_user, 'public.url_fetch_tasks', 'SELECT')
            AND NOT has_table_privilege(
                current_user, 'public.url_fetch_tasks',
                'INSERT,DELETE,TRUNCATE'
            )
        ) AS task_table_access,
        (
            SELECT bool_and(
                has_column_privilege(
                    current_user, 'public.url_fetch_tasks', column_name, 'UPDATE'
                )
            )
            FROM unnest(
                ARRAY[
                    'status', 'attempt_count', 'available_at',
                    'lease_expires_at', 'lease_token', 'last_error_code',
                    'content_type', 'size_bytes', 'source_sha256',
                    'source_file_id', 'started_at', 'completed_at',
                    'cancelled_at', 'updated_at'
                ]
            ) AS columns(column_name)
        ) AS task_update_access,
        (
            has_table_privilege(current_user, 'public.projects', 'SELECT')
            AND NOT has_table_privilege(
                current_user, 'public.projects',
                'INSERT,UPDATE,DELETE,TRUNCATE'
            )
        ) AS project_read_only,
        (
            has_table_privilege(current_user, 'public.documents', 'SELECT')
            AND NOT has_table_privilege(
                current_user, 'public.documents', 'INSERT,DELETE,TRUNCATE'
            )
        ) AS document_table_access,
        (
            SELECT bool_and(
                has_column_privilege(
                    current_user, 'public.documents', column_name, 'UPDATE'
                )
            )
            FROM unnest(
                ARRAY['source_file_id', 'document_type', 'status', 'updated_at']
            ) AS columns(column_name)
        ) AS document_update_access,
        (
            has_table_privilege(
                current_user, 'public.source_files', 'SELECT,INSERT'
            )
            AND NOT has_table_privilege(
                current_user, 'public.source_files', 'UPDATE,DELETE,TRUNCATE'
            )
        ) AS source_insert_only,
        (
            has_table_privilege(
                current_user, 'public.upload_sessions', 'SELECT,INSERT'
            )
            AND NOT has_table_privilege(
                current_user, 'public.upload_sessions', 'UPDATE,DELETE,TRUNCATE'
            )
        ) AS upload_insert_only,
        (
            has_table_privilege(
                current_user, 'public.document_versions', 'SELECT,INSERT'
            )
            AND NOT has_table_privilege(
                current_user, 'public.document_versions', 'UPDATE,DELETE,TRUNCATE'
            )
        ) AS version_insert_only,
        (
            has_table_privilege(current_user, 'public.audit_events', 'INSERT')
            AND NOT has_table_privilege(
                current_user, 'public.audit_events',
                'SELECT,UPDATE,DELETE,TRUNCATE'
            )
        ) AS audit_insert_only,
        (
            SELECT count(*) = 7
                AND bool_and(class.relrowsecurity)
                AND bool_and(class.relforcerowsecurity)
            FROM pg_class AS class
            JOIN pg_namespace AS namespace
              ON namespace.oid = class.relnamespace
            WHERE namespace.nspname = 'public'
              AND class.relname IN (
                  'url_fetch_tasks', 'projects', 'documents',
                  'source_files', 'upload_sessions',
                  'document_versions', 'audit_events'
              )
        ) AS forced_rls_present
    FROM pg_roles AS role
    JOIN pg_roles AS login ON login.rolname = session_user
    WHERE role.rolname = current_user
    """
)


def create_url_fetcher_engine(settings: UrlFetcherSettings) -> AsyncEngine:
    connect_args: dict[str, object] = {}
    engine_options: dict[str, object] = {}
    if settings.database_backend == "postgresql":
        connect_args["timeout"] = settings.database_connect_timeout_seconds
        connect_args["command_timeout"] = settings.database_command_timeout_seconds
        connect_args["server_settings"] = {
            "application_name": "akc-url-fetcher",
            "role": settings.url_database_role,
            "statement_timeout": str(settings.database_statement_timeout_ms),
            "lock_timeout": str(settings.database_lock_timeout_ms),
            "idle_in_transaction_session_timeout": str(
                settings.database_idle_transaction_timeout_ms
            ),
        }
        engine_options["pool_timeout"] = settings.database_pool_timeout_seconds
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args=connect_args,
        **engine_options,
    )
    if settings.database_backend == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


async def verify_url_fetcher_database(
    engine: AsyncEngine,
    settings: UrlFetcherSettings,
) -> UrlFetcherDatabaseCapability:
    if settings.database_backend == "sqlite":
        if settings.env == "production":
            raise UrlFetcherDatabasePrivilegeError(
                "sqlite_url_fetcher_adapter_forbidden_in_production"
            )
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            foreign_keys = await connection.scalar(text("PRAGMA foreign_keys"))
        if foreign_keys != 1:
            raise UrlFetcherDatabasePrivilegeError("sqlite_foreign_keys_disabled")
        return UrlFetcherDatabaseCapability(
            backend="sqlite",
            effective_role=None,
            login_role=None,
            bypass_rls=False,
            sqlite_test_adapter=True,
        )
    if settings.database_backend != "postgresql":
        raise UrlFetcherDatabasePrivilegeError("unsupported_url_fetcher_database")
    async with engine.connect() as connection:
        row = (await connection.execute(_POSTGRES_CAPABILITY_QUERY)).mappings().one_or_none()
    if row is None:
        raise UrlFetcherDatabasePrivilegeError("url_fetcher_role_not_found")
    required_true = (
        "bypass_rls",
        "effective_role_safe",
        "login_role_safe",
        "login_has_only_effective_role",
        "login_has_no_direct_table_acl",
        "application_tables_have_no_public_acl",
        "worker_owns_no_application_table",
        "login_cannot_create_in_public",
        "schema_usage",
        "task_table_access",
        "task_update_access",
        "project_read_only",
        "document_table_access",
        "document_update_access",
        "source_insert_only",
        "upload_insert_only",
        "version_insert_only",
        "audit_insert_only",
        "forced_rls_present",
    )
    failures = [name for name in required_true if not bool(row[name])]
    if str(row["effective_role"]) != settings.url_database_role:
        failures.append("effective_role")
    if bool(row["can_login"]):
        failures.append("role_must_be_nologin")
    if failures:
        raise UrlFetcherDatabasePrivilegeError(
            "url_fetcher_database_capability_missing:" + ",".join(sorted(failures))
        )
    return UrlFetcherDatabaseCapability(
        backend="postgresql",
        effective_role=str(row["effective_role"]),
        login_role=str(row["login_role"]),
        bypass_rls=True,
        sqlite_test_adapter=False,
    )
