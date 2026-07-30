"""Scheduler database engine and PostgreSQL RLS capability checks."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from akc_scheduler.settings import SchedulerSettings


class SchedulerDatabasePrivilegeError(RuntimeError):
    """The effective database role cannot safely run cross-tenant claims."""


@dataclass(frozen=True, slots=True)
class SchedulerDatabaseCapability:
    backend: str
    effective_role: str | None
    login_role: str | None
    bypass_rls: bool
    sqlite_test_adapter: bool
    purpose: str


_POSTGRES_CAPABILITY_QUERY = text(
    """
    SELECT
        current_user AS effective_role,
        session_user AS login_role,
        COALESCE(role.rolbypassrls, false) AS bypass_rls,
        COALESCE(role.rolcanlogin, true) AS can_login,
        NOT (
            role.rolsuper
            OR role.rolcreaterole
            OR role.rolcreatedb
            OR role.rolreplication
            OR role.rolinherit
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
            FROM pg_auth_members AS inherited_membership
            WHERE inherited_membership.member = role.oid
        ) AS effective_role_has_no_memberships,
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
              AND owned_class.relowner = login.oid
        ) AS login_owns_no_application_table,
        NOT EXISTS (
            SELECT 1
            FROM pg_class AS role_owned_class
            WHERE role_owned_class.relnamespace = 'public'::regnamespace
              AND role_owned_class.relkind IN ('r', 'p')
              AND role_owned_class.relname <> 'alembic_version'
              AND role_owned_class.relowner = role.oid
        ) AS effective_role_owns_no_application_table,
        (
            SELECT database.datdba <> login.oid
            FROM pg_database AS database
            WHERE database.datname = current_database()
        ) AS login_is_not_database_owner,
        (
            SELECT database.datdba <> role.oid
            FROM pg_database AS database
            WHERE database.datname = current_database()
        ) AS effective_role_is_not_database_owner,
        (
            SELECT namespace.nspowner <> role.oid
            FROM pg_namespace AS namespace
            WHERE namespace.nspname = 'public'
        ) AS effective_role_is_not_public_schema_owner,
        NOT has_schema_privilege(session_user, 'public', 'CREATE')
            AS login_cannot_create_in_public,
        has_schema_privilege(current_user, 'public', 'USAGE') AS schema_usage,
        NOT EXISTS (
            SELECT 1
            FROM pg_class AS granted_class
            CROSS JOIN LATERAL aclexplode(granted_class.relacl) AS granted_acl
            WHERE granted_class.relnamespace = 'public'::regnamespace
              AND granted_acl.grantee = role.oid
              AND (
                  granted_acl.is_grantable
                  OR NOT (
                      (
                          granted_class.relname = 'outbox_events'
                          AND granted_acl.privilege_type IN ('SELECT', 'DELETE')
                      )
                      OR (
                          granted_class.relname = 'webhook_endpoints'
                          AND granted_acl.privilege_type = 'SELECT'
                      )
                      OR (
                          granted_class.relname = 'webhook_deliveries'
                          AND granted_acl.privilege_type
                              IN ('SELECT', 'INSERT', 'DELETE')
                      )
                      OR (
                          granted_class.relname = 'job_events'
                          AND granted_acl.privilege_type IN ('SELECT', 'DELETE')
                      )
                      OR (
                          granted_class.relname = 'idempotency_records'
                          AND granted_acl.privilege_type IN ('SELECT', 'DELETE')
                      )
                      OR (
                          granted_class.relname IN (
                              'email_verification_tokens',
                              'email_verification_deliveries'
                          )
                          AND granted_acl.privilege_type IN ('SELECT', 'DELETE')
                      )
                  )
              )
        ) AS effective_table_acl_exact,
        NOT EXISTS (
            SELECT 1
            FROM pg_class AS column_class
            JOIN pg_attribute AS attribute
              ON attribute.attrelid = column_class.oid
            CROSS JOIN LATERAL aclexplode(attribute.attacl) AS column_acl
            WHERE column_class.relnamespace = 'public'::regnamespace
              AND column_acl.grantee = role.oid
              AND (
                  column_acl.is_grantable
                  OR column_acl.privilege_type <> 'UPDATE'
                  OR NOT (
                      (
                          column_class.relname = 'outbox_events'
                          AND attribute.attname IN (
                              'published_at', 'attempts', 'last_error'
                          )
                      )
                      OR (
                          column_class.relname = 'webhook_deliveries'
                          AND attribute.attname IN (
                              'status',
                              'attempts',
                              'next_attempt_at',
                              'last_status_code',
                              'last_error',
                              'delivered_at',
                              'dead_lettered_at',
                              'updated_at'
                          )
                      )
                      OR (
                          column_class.relname = 'email_verification_deliveries'
                          AND attribute.attname IN (
                              'status',
                              'attempts',
                              'available_at',
                              'last_error_code',
                              'provider_message_id',
                              'delivered_at',
                              'dead_lettered_at',
                              'updated_at'
                          )
                      )
                  )
              )
        ) AS effective_column_acl_exact,
        (
            has_table_privilege(
                current_user, 'public.outbox_events', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.outbox_events', 'DELETE'
            )
        ) AS outbox_table_access,
        has_column_privilege(
            current_user, 'public.outbox_events', 'published_at', 'UPDATE'
        ) AS outbox_update_published,
        has_column_privilege(
            current_user, 'public.outbox_events', 'attempts', 'UPDATE'
        ) AS outbox_update_attempts,
        has_column_privilege(
            current_user, 'public.outbox_events', 'last_error', 'UPDATE'
        ) AS outbox_update_error,
        has_table_privilege(
            current_user, 'public.webhook_endpoints', 'SELECT'
        ) AS endpoint_access,
        (
            has_table_privilege(
                current_user, 'public.webhook_deliveries', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.webhook_deliveries', 'INSERT'
            )
            AND has_table_privilege(
                current_user, 'public.webhook_deliveries', 'DELETE'
            )
        ) AS delivery_table_access,
        (
            has_table_privilege(
                current_user, 'public.job_events', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.job_events', 'DELETE'
            )
        ) AS job_event_retention_access,
        (
            has_table_privilege(
                current_user, 'public.idempotency_records', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.idempotency_records', 'DELETE'
            )
        ) AS idempotency_retention_access,
        (
            SELECT bool_and(
                has_column_privilege(
                    current_user,
                    'public.webhook_deliveries',
                    column_name,
                    'UPDATE'
                )
            )
            FROM unnest(
                ARRAY[
                    'status',
                    'attempts',
                    'next_attempt_at',
                    'last_status_code',
                    'last_error',
                    'delivered_at',
                    'dead_lettered_at',
                    'updated_at'
                ]
            ) AS columns(column_name)
        ) AS delivery_update_access,
        (
            SELECT count(*) = 5
                AND bool_and(class.relrowsecurity)
                AND bool_and(class.relforcerowsecurity)
            FROM pg_class AS class
            JOIN pg_namespace AS namespace
              ON namespace.oid = class.relnamespace
            WHERE namespace.nspname = 'public'
              AND class.relname IN (
                  'outbox_events',
                  'webhook_endpoints',
                  'webhook_deliveries',
                  'job_events',
                  'idempotency_records'
              )
        ) AS forced_rls_present
    FROM pg_roles AS role
    JOIN pg_roles AS login ON login.rolname = session_user
    WHERE role.rolname = current_user
    """
)


_POSTGRES_DISPATCH_CAPABILITY_QUERY = text(
    """
    SELECT
        current_user AS effective_role,
        session_user AS login_role,
        COALESCE(role.rolbypassrls, false) AS bypass_rls,
        COALESCE(role.rolcanlogin, true) AS can_login,
        NOT (
            role.rolsuper
            OR role.rolcreaterole
            OR role.rolcreatedb
            OR role.rolreplication
            OR role.rolinherit
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
            FROM pg_auth_members AS inherited_membership
            WHERE inherited_membership.member = role.oid
        ) AS effective_role_has_no_memberships,
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
              AND owned_class.relowner = login.oid
        ) AS login_owns_no_application_table,
        NOT EXISTS (
            SELECT 1
            FROM pg_class AS role_owned_class
            WHERE role_owned_class.relnamespace = 'public'::regnamespace
              AND role_owned_class.relkind IN ('r', 'p')
              AND role_owned_class.relname <> 'alembic_version'
              AND role_owned_class.relowner = role.oid
        ) AS effective_role_owns_no_application_table,
        (
            SELECT database.datdba <> login.oid
            FROM pg_database AS database
            WHERE database.datname = current_database()
        ) AS login_is_not_database_owner,
        (
            SELECT database.datdba <> role.oid
            FROM pg_database AS database
            WHERE database.datname = current_database()
        ) AS effective_role_is_not_database_owner,
        (
            SELECT namespace.nspowner <> role.oid
            FROM pg_namespace AS namespace
            WHERE namespace.nspname = 'public'
        ) AS effective_role_is_not_public_schema_owner,
        NOT has_schema_privilege(session_user, 'public', 'CREATE')
            AS login_cannot_create_in_public,
        has_schema_privilege(current_user, 'public', 'USAGE') AS schema_usage,
        NOT EXISTS (
            SELECT 1
            FROM pg_class AS granted_class
            CROSS JOIN LATERAL aclexplode(granted_class.relacl) AS granted_acl
            WHERE granted_class.relnamespace = 'public'::regnamespace
              AND granted_acl.grantee = role.oid
              AND (
                  granted_acl.is_grantable
                  OR NOT (
                      (
                          granted_class.relname = 'outbox_events'
                          AND granted_acl.privilege_type IN ('SELECT', 'INSERT')
                      )
                      OR (
                          granted_class.relname IN (
                              'processing_jobs',
                              'tenants',
                              'projects',
                              'documents',
                              'source_files',
                              'blocks',
                              'pages',
                              'feature_flags',
                              'model_registry'
                          )
                          AND granted_acl.privilege_type = 'SELECT'
                      )
                      OR (
                          granted_class.relname IN (
                              'knowledge_notes',
                              'document_semantic_classifications',
                              'credit_accounts',
                              'credit_ledger',
                              'gpu_provider_invocations',
                              'gpu_invocation_events',
                              'relations',
                              'page_attempts',
                              'page_attempt_transition_events'
                          )
                          AND granted_acl.privilege_type IN ('SELECT', 'INSERT')
                      )
                      OR (
                          granted_class.relname = 'job_events'
                          AND granted_acl.privilege_type = 'INSERT'
                      )
                  )
              )
        ) AS effective_table_acl_exact,
        NOT EXISTS (
            SELECT 1
            FROM pg_class AS column_class
            JOIN pg_attribute AS attribute
              ON attribute.attrelid = column_class.oid
            CROSS JOIN LATERAL aclexplode(attribute.attacl) AS column_acl
            WHERE column_class.relnamespace = 'public'::regnamespace
              AND column_acl.grantee = role.oid
              AND (
                  column_acl.is_grantable
                  OR column_acl.privilege_type <> 'UPDATE'
                  OR NOT (
                      (
                          column_class.relname = 'outbox_events'
                          AND attribute.attname IN (
                              'available_at',
                              'published_at',
                              'dead_lettered_at',
                              'attempts',
                              'last_error'
                          )
                      )
                      OR (
                          column_class.relname = 'processing_jobs'
                          AND attribute.attname IN (
                              'status',
                              'started_at',
                              'completed_at',
                              'progress',
                              'cost_actual',
                              'event_sequence',
                              'error'
                          )
                      )
                      OR (
                          column_class.relname = 'pages'
                          AND attribute.attname IN ('status', 'updated_at')
                      )
                      OR (
                          column_class.relname = 'credit_accounts'
                          AND attribute.attname IN (
                              'balance', 'reserved', 'version', 'updated_at'
                          )
                      )
                      OR (
                          column_class.relname = 'page_attempts'
                          AND attribute.attname IN (
                              'provider_invocation_id', 'status',
                              'quality_vector', 'quality_findings',
                              'quality_evaluation', 'escalation_decision',
                              'event_sequence', 'completed_at', 'updated_at'
                          )
                      )
                  )
              )
        ) AS effective_column_acl_exact,
        (
            has_table_privilege(
                current_user, 'public.outbox_events', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.outbox_events', 'INSERT'
            )
        ) AS outbox_table_access,
        (
            SELECT bool_and(
                has_column_privilege(
                    current_user,
                    'public.outbox_events',
                    column_name,
                    'UPDATE'
                )
            )
            FROM unnest(
                ARRAY[
                    'available_at',
                    'published_at',
                    'dead_lettered_at',
                    'attempts',
                    'last_error'
                ]
            ) AS columns(column_name)
        ) AS outbox_update_access,
        (
            SELECT bool_and(
                has_column_privilege(
                    current_user,
                    'public.processing_jobs',
                    column_name,
                    'UPDATE'
                )
            )
            FROM unnest(
                ARRAY[
                    'status',
                    'started_at',
                    'completed_at',
                    'progress',
                    'cost_actual',
                    'event_sequence',
                    'error'
                ]
            ) AS columns(column_name)
        ) AS job_update_access,
        has_table_privilege(
            current_user, 'public.processing_jobs', 'SELECT'
        ) AS job_select_access,
        has_table_privilege(
            current_user, 'public.documents', 'SELECT'
        ) AS document_select_access,
        has_table_privilege(
            current_user, 'public.blocks', 'SELECT'
        ) AS block_select_access,
        has_table_privilege(
            current_user, 'public.pages', 'SELECT'
        ) AS page_select_access,
        (
            has_table_privilege(current_user, 'public.tenants', 'SELECT')
            AND has_table_privilege(current_user, 'public.projects', 'SELECT')
            AND has_table_privilege(
                current_user, 'public.source_files', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.feature_flags', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.model_registry', 'SELECT'
            )
        ) AS routing_context_access,
        (
            has_table_privilege(
                current_user, 'public.page_attempts', 'SELECT,INSERT'
            )
            AND has_table_privilege(
                current_user, 'public.page_attempt_transition_events',
                'SELECT,INSERT'
            )
            AND NOT has_table_privilege(
                current_user, 'public.page_attempt_transition_events',
                'UPDATE,DELETE,TRUNCATE'
            )
            AND (
                SELECT bool_and(
                    has_column_privilege(
                        current_user, 'public.page_attempts',
                        column_name, 'UPDATE'
                    )
                )
                FROM unnest(
                    ARRAY[
                        'provider_invocation_id', 'status', 'quality_vector',
                        'quality_findings', 'quality_evaluation',
                        'escalation_decision', 'event_sequence',
                        'completed_at', 'updated_at'
                    ]
                ) AS columns(column_name)
            )
        ) AS page_attempt_access,
        (
            has_column_privilege(
                current_user, 'public.pages', 'status', 'UPDATE'
            )
            AND has_column_privilege(
                current_user, 'public.pages', 'updated_at', 'UPDATE'
            )
        ) AS page_update_access,
        has_table_privilege(
            current_user, 'public.job_events', 'INSERT'
        ) AS job_event_insert_access,
        (
            has_table_privilege(
                current_user, 'public.knowledge_notes', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.knowledge_notes', 'INSERT'
            )
        ) AS knowledge_note_access,
        (
            has_table_privilege(
                current_user,
                'public.document_semantic_classifications',
                'SELECT'
            )
            AND has_table_privilege(
                current_user,
                'public.document_semantic_classifications',
                'INSERT'
            )
        ) AS semantic_classification_access,
        (
            has_table_privilege(
                current_user, 'public.relations', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.relations', 'INSERT'
            )
        ) AS relation_access,
        (
            has_table_privilege(
                current_user, 'public.gpu_provider_invocations', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.gpu_provider_invocations', 'INSERT'
            )
            AND has_table_privilege(
                current_user, 'public.gpu_invocation_events', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.gpu_invocation_events', 'INSERT'
            )
        ) AS gpu_invocation_access,
        (
            has_table_privilege(
                current_user, 'public.credit_ledger', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.credit_ledger', 'INSERT'
            )
        ) AS credit_ledger_access,
        (
            has_table_privilege(
                current_user, 'public.credit_accounts', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.credit_accounts', 'INSERT'
            )
        ) AS credit_account_table_access,
        (
            SELECT bool_and(
                has_column_privilege(
                    current_user,
                    'public.credit_accounts',
                    column_name,
                    'UPDATE'
                )
            )
            FROM unnest(
                ARRAY['balance', 'reserved', 'version', 'updated_at']
            ) AS columns(column_name)
        ) AS credit_account_update_access,
        (
            SELECT count(*) = 19
                AND bool_and(class.relrowsecurity)
                AND bool_and(class.relforcerowsecurity)
            FROM pg_class AS class
            JOIN pg_namespace AS namespace
              ON namespace.oid = class.relnamespace
            WHERE namespace.nspname = 'public'
              AND class.relname IN (
                  'outbox_events',
                  'processing_jobs',
                  'documents',
                  'blocks',
                  'pages',
                  'job_events',
                  'knowledge_notes',
                  'document_semantic_classifications',
                  'relations',
                  'credit_accounts',
                  'credit_ledger',
                  'gpu_provider_invocations',
                  'gpu_invocation_events',
                  'tenants',
                  'projects',
                  'source_files',
                  'feature_flags',
                  'page_attempts',
                  'page_attempt_transition_events'
              )
        ) AS forced_rls_present
    FROM pg_roles AS role
    JOIN pg_roles AS login ON login.rolname = session_user
    WHERE role.rolname = current_user
    """
)


_POSTGRES_DELETION_CAPABILITY_QUERY = text(
    """
    SELECT
        current_user AS effective_role,
        session_user AS login_role,
        role.rolbypassrls AS bypass_rls,
        role.rolcanlogin AS can_login,
        NOT (
            role.rolsuper OR role.rolcreaterole OR role.rolcreatedb
            OR role.rolreplication OR role.rolinherit
        ) AS effective_role_safe,
        (
            login.rolcanlogin AND NOT login.rolsuper
            AND NOT login.rolcreaterole AND NOT login.rolcreatedb
            AND NOT login.rolreplication AND NOT login.rolbypassrls
            AND NOT login.rolinherit
        ) AS login_role_safe,
        (
            pg_has_role(login.oid, role.oid, 'MEMBER')
            AND NOT EXISTS (
                SELECT 1 FROM pg_auth_members AS membership
                WHERE membership.member = login.oid
                  AND (
                    membership.roleid <> role.oid
                    OR membership.admin_option
                  )
            )
        ) AS login_has_only_effective_role,
        NOT EXISTS (
            SELECT 1 FROM pg_auth_members AS inherited_membership
            WHERE inherited_membership.member = role.oid
        ) AS effective_role_has_no_memberships,
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
            SELECT 1 FROM pg_class AS owned_class
            WHERE owned_class.relnamespace = 'public'::regnamespace
              AND owned_class.relkind IN ('r', 'p')
              AND owned_class.relname <> 'alembic_version'
              AND owned_class.relowner = login.oid
        ) AS login_owns_no_application_table,
        NOT EXISTS (
            SELECT 1 FROM pg_class AS role_owned_class
            WHERE role_owned_class.relnamespace = 'public'::regnamespace
              AND role_owned_class.relkind IN ('r', 'p')
              AND role_owned_class.relname <> 'alembic_version'
              AND role_owned_class.relowner = role.oid
        ) AS effective_role_owns_no_application_table,
        (
            SELECT database.datdba <> login.oid
            FROM pg_database AS database
            WHERE database.datname = current_database()
        ) AS login_is_not_database_owner,
        (
            SELECT database.datdba <> role.oid
            FROM pg_database AS database
            WHERE database.datname = current_database()
        ) AS effective_role_is_not_database_owner,
        (
            SELECT namespace.nspowner <> role.oid
            FROM pg_namespace AS namespace
            WHERE namespace.nspname = 'public'
        ) AS effective_role_is_not_public_schema_owner,
        NOT has_schema_privilege(session_user, 'public', 'CREATE')
            AS login_cannot_create_in_public,
        has_schema_privilege(current_user, 'public', 'USAGE') AS schema_usage,
        (
            has_table_privilege(
                current_user, 'public.deletion_requests', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.deletion_requests', 'INSERT'
            )
            AND has_table_privilege(
                current_user, 'public.deletion_objects', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.deletion_objects', 'INSERT'
            )
            AND has_table_privilege(
                current_user, 'public.deletion_attempts', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.deletion_attempts', 'INSERT'
            )
            AND has_table_privilege(
                current_user, 'public.deletion_receipts', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.deletion_receipts', 'INSERT'
            )
            AND has_table_privilege(
                current_user, 'public.outbox_events', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.outbox_events', 'INSERT'
            )
            AND has_table_privilege(
                current_user, 'public.audit_events', 'INSERT'
            )
            AND has_table_privilege(
                current_user, 'public.credit_ledger', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.credit_ledger', 'INSERT'
            )
            AND has_table_privilege(
                current_user, 'public.credit_accounts', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.credit_accounts', 'INSERT'
            )
            AND has_table_privilege(
                current_user, 'public.job_events', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.job_events', 'INSERT'
            )
        ) AS evidence_access,
        (
            SELECT bool_and(
                has_table_privilege(
                    current_user,
                    'public.' || quote_ident(table_name),
                    'SELECT'
                )
            )
            FROM unnest(
                ARRAY[
                    'tenants', 'projects', 'documents', 'document_versions',
                    'pages', 'page_assets', 'page_attempts',
                    'page_attempt_transition_events', 'blocks', 'block_revisions',
                    'upload_sessions', 'source_files', 'processing_jobs',
                    'analysis_tasks', 'url_fetch_tasks', 'job_events', 'review_items',
                    'knowledge_notes', 'entities', 'relations', 'exports',
                    'credit_accounts', 'credit_ledger', 'outbox_events',
                    'deletion_requests', 'deletion_objects',
                    'deletion_attempts', 'deletion_receipts'
                ]
            ) AS tables(table_name)
        ) AS manifest_access,
        (
            has_table_privilege(current_user, 'public.projects', 'SELECT')
            AND has_table_privilege(current_user, 'public.projects', 'DELETE')
            AND has_table_privilege(
                current_user, 'public.documents', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.documents', 'DELETE'
            )
            AND has_table_privilege(
                current_user, 'public.source_files', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.source_files', 'DELETE'
            )
            AND has_table_privilege(
                current_user, 'public.upload_sessions', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.upload_sessions', 'DELETE'
            )
            AND has_table_privilege(
                current_user, 'public.knowledge_notes', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.knowledge_notes', 'DELETE'
            )
            AND has_table_privilege(
                current_user, 'public.processing_jobs', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.gpu_provider_invocations', 'SELECT'
            )
        ) AS target_access,
        (
            SELECT bool_and(
                has_column_privilege(
                    current_user,
                    'public.deletion_requests',
                    column_name,
                    'UPDATE'
                )
            )
            FROM unnest(
                ARRAY[
                    'state', 'deleted_count', 'attempts', 'last_error_code',
                    'lease_token', 'lease_expires_at', 'updated_at',
                    'completed_at'
                ]
            ) AS columns(column_name)
        ) AS request_update_access,
        (
            SELECT bool_and(
                has_column_privilege(
                    current_user,
                    'public.deletion_objects',
                    column_name,
                    'UPDATE'
                )
            )
            FROM unnest(
                ARRAY['state', 'attempts', 'last_error_code', 'purged_at']
            ) AS columns(column_name)
        ) AS object_update_access,
        (
            SELECT bool_and(
                has_column_privilege(
                    current_user,
                    'public.outbox_events',
                    column_name,
                    'UPDATE'
                )
            )
            FROM unnest(
                ARRAY[
                    'available_at', 'published_at', 'dead_lettered_at',
                    'attempts', 'last_error'
                ]
            ) AS columns(column_name)
        ) AS outbox_update_access,
        (
            SELECT bool_and(
                has_column_privilege(
                    current_user,
                    'public.' || quote_ident(table_name),
                    column_name,
                    'UPDATE'
                )
            )
            FROM (
                VALUES
                    ('projects', 'deletion_requested_at'),
                    ('projects', 'updated_at'),
                    ('documents', 'status'),
                    ('documents', 'deletion_requested_at'),
                    ('documents', 'updated_at'),
                    ('processing_jobs', 'status'),
                    ('processing_jobs', 'completed_at'),
                    ('processing_jobs', 'event_sequence'),
                    ('processing_jobs', 'error'),
                    ('analysis_tasks', 'status'),
                    ('analysis_tasks', 'lease_expires_at'),
                    ('analysis_tasks', 'lease_token'),
                    ('analysis_tasks', 'last_error_code'),
                    ('analysis_tasks', 'completed_at'),
                    ('analysis_tasks', 'updated_at'),
                    ('gpu_provider_invocations', 'status'),
                    ('gpu_provider_invocations', 'available_at'),
                    ('gpu_provider_invocations', 'lease_expires_at'),
                    ('gpu_provider_invocations', 'lease_token'),
                    ('gpu_provider_invocations', 'cancellation_reason'),
                    ('gpu_provider_invocations', 'last_error_code'),
                    ('gpu_provider_invocations', 'completed_at'),
                    ('gpu_provider_invocations', 'updated_at'),
                    ('url_fetch_tasks', 'status'),
                    ('url_fetch_tasks', 'available_at'),
                    ('url_fetch_tasks', 'lease_expires_at'),
                    ('url_fetch_tasks', 'lease_token'),
                    ('url_fetch_tasks', 'last_error_code'),
                    ('url_fetch_tasks', 'completed_at'),
                    ('url_fetch_tasks', 'cancelled_at'),
                    ('url_fetch_tasks', 'updated_at'),
                    ('credit_accounts', 'balance'),
                    ('credit_accounts', 'reserved'),
                    ('credit_accounts', 'version'),
                    ('credit_accounts', 'updated_at'),
                    ('deletion_attempts', 'outcome'),
                    ('deletion_attempts', 'failure_hashes'),
                    ('deletion_attempts', 'error_code'),
                    ('deletion_attempts', 'completed_at')
            ) AS columns(table_name, column_name)
        ) AS mutation_update_access,
        (
            NOT has_table_privilege(current_user, 'public.audit_events', 'UPDATE')
            AND NOT has_table_privilege(current_user, 'public.audit_events', 'DELETE')
            AND NOT has_table_privilege(
                current_user, 'public.deletion_receipts', 'UPDATE'
            )
            AND NOT has_table_privilege(
                current_user, 'public.deletion_receipts', 'DELETE'
            )
            AND NOT has_table_privilege(current_user, 'public.users', 'SELECT')
            AND NOT has_table_privilege(current_user, 'public.users', 'INSERT')
            AND NOT has_table_privilege(current_user, 'public.users', 'UPDATE')
            AND NOT has_table_privilege(current_user, 'public.users', 'DELETE')
            AND NOT has_table_privilege(current_user, 'public.api_keys', 'SELECT')
            AND NOT has_table_privilege(current_user, 'public.api_keys', 'INSERT')
            AND NOT has_table_privilege(current_user, 'public.api_keys', 'UPDATE')
            AND NOT has_table_privilege(current_user, 'public.api_keys', 'DELETE')
            AND NOT has_table_privilege(
                current_user, 'public.webhook_endpoints', 'SELECT'
            )
            AND NOT has_table_privilege(
                current_user, 'public.webhook_endpoints', 'INSERT'
            )
            AND NOT has_table_privilege(
                current_user, 'public.webhook_endpoints', 'UPDATE'
            )
            AND NOT has_table_privilege(
                current_user, 'public.webhook_endpoints', 'DELETE'
            )
            AND NOT EXISTS (
                SELECT 1
                FROM unnest(
                    ARRAY[
                        'memberships', 'idempotency_records',
                        'webhook_deliveries', 'feature_flags'
                    ]
                ) AS forbidden_tables(table_name)
                CROSS JOIN unnest(
                    ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']
                ) AS forbidden_privileges(privilege_name)
                WHERE has_table_privilege(
                    current_user,
                    'public.' || quote_ident(table_name),
                    privilege_name
                )
            )
        ) AS forbidden_access_absent,
        (
            SELECT count(*) = 3
                AND bool_and(class.relrowsecurity)
                AND bool_and(class.relforcerowsecurity)
            FROM pg_class AS class
            JOIN pg_namespace AS namespace
              ON namespace.oid = class.relnamespace
            WHERE namespace.nspname = 'public'
              AND class.relname IN (
                  'deletion_requests', 'deletion_objects', 'deletion_attempts'
              )
        ) AS forced_rls_present
    FROM pg_roles AS role
    JOIN pg_roles AS login ON login.rolname = session_user
    WHERE role.rolname = current_user
    """
)


_POSTGRES_GPU_CAPABILITY_QUERY = text(
    """
    SELECT
        current_user AS effective_role,
        session_user AS login_role,
        role.rolbypassrls AS bypass_rls,
        role.rolcanlogin AS can_login,
        NOT (
            role.rolsuper OR role.rolcreaterole OR role.rolcreatedb
            OR role.rolreplication OR role.rolinherit
        ) AS effective_role_safe,
        (
            login.rolcanlogin AND NOT login.rolsuper
            AND NOT login.rolcreaterole AND NOT login.rolcreatedb
            AND NOT login.rolreplication AND NOT login.rolbypassrls
            AND NOT login.rolinherit
        ) AS login_role_safe,
        (
            pg_has_role(login.oid, role.oid, 'MEMBER')
            AND NOT EXISTS (
                SELECT 1 FROM pg_auth_members AS membership
                WHERE membership.member = login.oid
                  AND (
                    membership.roleid <> role.oid
                    OR membership.admin_option
                  )
            )
        ) AS login_has_only_effective_role,
        NOT EXISTS (
            SELECT 1 FROM pg_auth_members AS inherited_membership
            WHERE inherited_membership.member = role.oid
        ) AS effective_role_has_no_memberships,
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
            SELECT 1 FROM pg_class AS owned_class
            WHERE owned_class.relnamespace = 'public'::regnamespace
              AND owned_class.relkind IN ('r', 'p')
              AND owned_class.relname <> 'alembic_version'
              AND owned_class.relowner = login.oid
        ) AS login_owns_no_application_table,
        NOT EXISTS (
            SELECT 1 FROM pg_class AS role_owned_class
            WHERE role_owned_class.relnamespace = 'public'::regnamespace
              AND role_owned_class.relkind IN ('r', 'p')
              AND role_owned_class.relname <> 'alembic_version'
              AND role_owned_class.relowner = role.oid
        ) AS effective_role_owns_no_application_table,
        (
            SELECT database.datdba <> login.oid
            FROM pg_database AS database
            WHERE database.datname = current_database()
        ) AS login_is_not_database_owner,
        (
            SELECT database.datdba <> role.oid
            FROM pg_database AS database
            WHERE database.datname = current_database()
        ) AS effective_role_is_not_database_owner,
        (
            SELECT namespace.nspowner <> role.oid
            FROM pg_namespace AS namespace
            WHERE namespace.nspname = 'public'
        ) AS effective_role_is_not_public_schema_owner,
        NOT has_schema_privilege(session_user, 'public', 'CREATE')
            AS login_cannot_create_in_public,
        has_schema_privilege(current_user, 'public', 'USAGE') AS schema_usage,
        NOT EXISTS (
            SELECT 1
            FROM pg_class AS granted_class
            CROSS JOIN LATERAL aclexplode(granted_class.relacl) AS granted_acl
            WHERE granted_class.relnamespace = 'public'::regnamespace
              AND granted_acl.grantee = role.oid
              AND (
                  granted_acl.is_grantable
                  OR NOT (
                      (
                          granted_class.relname IN (
                              'gpu_provider_invocations',
                              'gpu_provider_attempts',
                              'gpu_invocation_events',
                              'processing_jobs',
                              'projects',
                              'documents',
                              'outbox_events',
                              'model_registry'
                          )
                          AND granted_acl.privilege_type = 'SELECT'
                      )
                      OR (
                          granted_class.relname IN (
                              'gpu_provider_attempts',
                              'gpu_invocation_events',
                              'outbox_events',
                              'audit_events',
                              'job_events'
                          )
                          AND granted_acl.privilege_type = 'INSERT'
                      )
                  )
              )
        ) AS effective_table_acl_exact,
        NOT EXISTS (
            SELECT 1
            FROM pg_class AS column_class
            JOIN pg_attribute AS attribute
              ON attribute.attrelid = column_class.oid
            CROSS JOIN LATERAL aclexplode(attribute.attacl) AS column_acl
            WHERE column_class.relnamespace = 'public'::regnamespace
              AND column_acl.grantee = role.oid
              AND (
                  column_acl.is_grantable
                  OR column_acl.privilege_type <> 'UPDATE'
                      OR NOT (
                          (
                              column_class.relname = 'gpu_provider_invocations'
                          AND attribute.attname IN (
                              'status', 'attempt_count',
                              'cancel_attempt_count', 'available_at',
                              'lease_expires_at', 'lease_token',
                              'provider_job_id', 'provider_status',
                              'provider_deadline_at',
                              'object_grant_expires_at',
                              'provider_callback_id',
                              'provider_callback_sha256',
                              'cancellation_reason', 'last_error_code',
                              'result_manifest', 'result_manifest_sha256',
                              'completion_source', 'event_sequence',
                              'started_at', 'completed_at', 'updated_at'
                          )
                      )
                      OR (
                          column_class.relname = 'gpu_provider_attempts'
                          AND attribute.attname IN (
                              'status', 'provider_job_id',
                              'provider_response_sha256',
                              'result_manifest_sha256', 'error_code',
                              'retryable', 'submitted_at', 'last_polled_at',
                                  'completed_at'
                              )
                          )
                          OR (
                              column_class.relname = 'processing_jobs'
                              AND attribute.attname IN (
                                  'progress', 'event_sequence'
                              )
                          )
                      )
                  )
        ) AS effective_column_acl_exact,
        (
            has_table_privilege(
                current_user, 'public.gpu_provider_invocations', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.gpu_provider_attempts', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.gpu_provider_attempts', 'INSERT'
            )
            AND has_table_privilege(
                current_user, 'public.gpu_invocation_events', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.gpu_invocation_events', 'INSERT'
            )
            AND has_table_privilege(
                current_user, 'public.processing_jobs', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.projects', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.documents', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.outbox_events', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.outbox_events', 'INSERT'
            )
            AND has_table_privilege(
                current_user, 'public.model_registry', 'SELECT'
            )
            AND has_table_privilege(
                current_user, 'public.job_events', 'INSERT'
            )
            AND has_table_privilege(
                current_user, 'public.audit_events', 'INSERT'
            )
            AND has_column_privilege(
                current_user, 'public.processing_jobs', 'progress', 'UPDATE'
            )
            AND has_column_privilege(
                current_user,
                'public.processing_jobs',
                'event_sequence',
                'UPDATE'
            )
        ) AS required_table_access,
        (
            SELECT count(*) = 3
                AND bool_and(class.relrowsecurity)
                AND bool_and(class.relforcerowsecurity)
            FROM pg_class AS class
            JOIN pg_namespace AS namespace
              ON namespace.oid = class.relnamespace
            WHERE namespace.nspname = 'public'
              AND class.relname IN (
                  'gpu_provider_invocations',
                  'gpu_provider_attempts',
                  'gpu_invocation_events'
              )
        ) AS forced_rls_present
    FROM pg_roles AS role
    JOIN pg_roles AS login ON login.rolname = session_user
    WHERE role.rolname = current_user
    """
)


def _create_role_engine(
    settings: SchedulerSettings,
    *,
    application_name: str,
    role: str,
) -> AsyncEngine:
    connect_args: dict[str, object] = {}
    engine_options: dict[str, object] = {}
    if settings.database_backend == "postgresql":
        connect_args["timeout"] = settings.database_connect_timeout_seconds
        connect_args["command_timeout"] = settings.database_command_timeout_seconds
        connect_args["server_settings"] = {
            "application_name": application_name,
            "role": role,
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


def create_scheduler_engine(settings: SchedulerSettings) -> AsyncEngine:
    """Create an engine assuming the webhook scheduler's non-login role."""

    return _create_role_engine(
        settings,
        application_name="akc-scheduler",
        role=settings.scheduler_database_role,
    )


def create_dispatch_engine(settings: SchedulerSettings) -> AsyncEngine:
    """Create an engine assuming the isolated compile-dispatch role."""

    return _create_role_engine(
        settings,
        application_name="akc-dispatch-worker",
        role=settings.dispatch_database_role,
    )


def create_deletion_engine(settings: SchedulerSettings) -> AsyncEngine:
    """Create an engine assuming the isolated destructive deletion role."""

    return _create_role_engine(
        settings,
        application_name="akc-deletion-worker",
        role=settings.deletion_database_role,
    )


def create_gpu_engine(settings: SchedulerSettings) -> AsyncEngine:
    """Create an engine assuming the isolated GPU control-plane role."""

    return _create_role_engine(
        settings,
        application_name="akc-gpu-worker",
        role=settings.gpu_database_role,
    )


def _role_safety_failures(
    row: object,
    *,
    require_exact_acl: bool = True,
) -> list[str]:
    mapping = row
    required: tuple[str, ...] = (
        "bypass_rls",
        "effective_role_safe",
        "login_role_safe",
        "login_has_only_effective_role",
        "effective_role_has_no_memberships",
        "login_has_no_direct_table_acl",
        "application_tables_have_no_public_acl",
        "login_owns_no_application_table",
        "effective_role_owns_no_application_table",
        "login_is_not_database_owner",
        "effective_role_is_not_database_owner",
        "effective_role_is_not_public_schema_owner",
        "login_cannot_create_in_public",
        "schema_usage",
    )
    if require_exact_acl:
        required += (
            "effective_table_acl_exact",
            "effective_column_acl_exact",
        )
    return [flag for flag in required if not bool(mapping[flag])]  # type: ignore[index]


async def _sqlite_capability(
    engine: AsyncEngine,
    settings: SchedulerSettings,
    *,
    purpose: str,
) -> SchedulerDatabaseCapability:
    if settings.env == "production":
        raise SchedulerDatabasePrivilegeError("sqlite_scheduler_adapter_forbidden_in_production")
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
        foreign_keys = await connection.scalar(text("PRAGMA foreign_keys"))
    if foreign_keys != 1:
        raise SchedulerDatabasePrivilegeError("sqlite_foreign_keys_disabled")
    return SchedulerDatabaseCapability(
        backend="sqlite",
        effective_role=None,
        login_role=None,
        bypass_rls=False,
        sqlite_test_adapter=True,
        purpose=purpose,
    )


async def verify_scheduler_database(
    engine: AsyncEngine,
    settings: SchedulerSettings,
) -> SchedulerDatabaseCapability:
    """Fail closed unless PostgreSQL uses the narrowly granted BYPASSRLS role."""

    if settings.database_backend == "sqlite":
        return await _sqlite_capability(engine, settings, purpose="webhook")
    if settings.database_backend != "postgresql":
        raise SchedulerDatabasePrivilegeError("unsupported_scheduler_database")

    async with engine.connect() as connection:
        row = (await connection.execute(_POSTGRES_CAPABILITY_QUERY)).mappings().one_or_none()
    if row is None:
        raise SchedulerDatabasePrivilegeError("scheduler_role_not_found")

    required_flags = (
        "outbox_table_access",
        "outbox_update_published",
        "outbox_update_attempts",
        "outbox_update_error",
        "endpoint_access",
        "delivery_table_access",
        "job_event_retention_access",
        "idempotency_retention_access",
        "delivery_update_access",
        "forced_rls_present",
    )
    failures = _role_safety_failures(row)
    failures.extend(flag for flag in required_flags if not bool(row[flag]))
    if str(row["effective_role"]) != settings.scheduler_database_role:
        failures.append("effective_role")
    if bool(row["can_login"]):
        failures.append("role_must_be_nologin")
    if failures:
        raise SchedulerDatabasePrivilegeError(
            "scheduler_database_capability_missing:" + ",".join(sorted(failures))
        )
    return SchedulerDatabaseCapability(
        backend="postgresql",
        effective_role=str(row["effective_role"]),
        login_role=str(row["login_role"]),
        bypass_rls=True,
        sqlite_test_adapter=False,
        purpose="webhook",
    )


async def verify_dispatch_database(
    engine: AsyncEngine,
    settings: SchedulerSettings,
) -> SchedulerDatabaseCapability:
    """Fail closed unless the compile adapter has only its required grants."""

    if settings.database_backend == "sqlite":
        return await _sqlite_capability(engine, settings, purpose="dispatch")
    if settings.database_backend != "postgresql":
        raise SchedulerDatabasePrivilegeError("unsupported_dispatch_database")

    async with engine.connect() as connection:
        row = (
            (await connection.execute(_POSTGRES_DISPATCH_CAPABILITY_QUERY)).mappings().one_or_none()
        )
    if row is None:
        raise SchedulerDatabasePrivilegeError("dispatch_role_not_found")

    required_flags = (
        "outbox_table_access",
        "outbox_update_access",
        "job_update_access",
        "job_select_access",
        "document_select_access",
        "block_select_access",
        "page_select_access",
        "routing_context_access",
        "page_attempt_access",
        "page_update_access",
        "job_event_insert_access",
        "knowledge_note_access",
        "semantic_classification_access",
        "relation_access",
        "gpu_invocation_access",
        "credit_ledger_access",
        "credit_account_table_access",
        "credit_account_update_access",
        "forced_rls_present",
    )
    failures = _role_safety_failures(row)
    failures.extend(flag for flag in required_flags if not bool(row[flag]))
    if str(row["effective_role"]) != settings.dispatch_database_role:
        failures.append("effective_role")
    if bool(row["can_login"]):
        failures.append("role_must_be_nologin")
    if failures:
        raise SchedulerDatabasePrivilegeError(
            "dispatch_database_capability_missing:" + ",".join(sorted(failures))
        )
    return SchedulerDatabaseCapability(
        backend="postgresql",
        effective_role=str(row["effective_role"]),
        login_role=str(row["login_role"]),
        bypass_rls=True,
        sqlite_test_adapter=False,
        purpose="dispatch",
    )


async def verify_deletion_database(
    engine: AsyncEngine,
    settings: SchedulerSettings,
) -> SchedulerDatabaseCapability:
    """Fail closed unless the deletion worker has only its bounded authority."""

    if settings.database_backend == "sqlite":
        return await _sqlite_capability(engine, settings, purpose="deletion")
    if settings.database_backend != "postgresql":
        raise SchedulerDatabasePrivilegeError("unsupported_deletion_database")

    async with engine.connect() as connection:
        row = (
            (await connection.execute(_POSTGRES_DELETION_CAPABILITY_QUERY)).mappings().one_or_none()
        )
    if row is None:
        raise SchedulerDatabasePrivilegeError("deletion_role_not_found")
    failures = _role_safety_failures(row, require_exact_acl=False)
    for flag in (
        "evidence_access",
        "manifest_access",
        "target_access",
        "request_update_access",
        "object_update_access",
        "outbox_update_access",
        "mutation_update_access",
        "forbidden_access_absent",
        "forced_rls_present",
    ):
        if not bool(row[flag]):
            failures.append(flag)
    if str(row["effective_role"]) != settings.deletion_database_role:
        failures.append("effective_role")
    if bool(row["can_login"]):
        failures.append("role_must_be_nologin")
    if failures:
        raise SchedulerDatabasePrivilegeError(
            "deletion_database_capability_missing:" + ",".join(sorted(failures))
        )
    return SchedulerDatabaseCapability(
        backend="postgresql",
        effective_role=str(row["effective_role"]),
        login_role=str(row["login_role"]),
        bypass_rls=True,
        sqlite_test_adapter=False,
        purpose="deletion",
    )


async def verify_gpu_database(
    engine: AsyncEngine,
    settings: SchedulerSettings,
) -> SchedulerDatabaseCapability:
    """Fail closed unless GPU polling has only its bounded durable-job grants."""

    if settings.database_backend == "sqlite":
        return await _sqlite_capability(engine, settings, purpose="gpu")
    if settings.database_backend != "postgresql":
        raise SchedulerDatabasePrivilegeError("unsupported_gpu_database")
    async with engine.connect() as connection:
        row = (await connection.execute(_POSTGRES_GPU_CAPABILITY_QUERY)).mappings().one_or_none()
    if row is None:
        raise SchedulerDatabasePrivilegeError("gpu_role_not_found")
    failures = _role_safety_failures(row)
    for flag in ("required_table_access", "forced_rls_present"):
        if not bool(row[flag]):
            failures.append(flag)
    if str(row["effective_role"]) != settings.gpu_database_role:
        failures.append("effective_role")
    if bool(row["can_login"]):
        failures.append("role_must_be_nologin")
    if failures:
        raise SchedulerDatabasePrivilegeError(
            "gpu_database_capability_missing:" + ",".join(sorted(failures))
        )
    return SchedulerDatabaseCapability(
        backend="postgresql",
        effective_role=str(row["effective_role"]),
        login_role=str(row["login_role"]),
        bypass_rls=True,
        sqlite_test_adapter=False,
        purpose="gpu",
    )
