DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'akc_scheduler') THEN
        CREATE ROLE akc_scheduler
            NOLOGIN NOINHERIT BYPASSRLS
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'akc_dispatch_worker') THEN
        CREATE ROLE akc_dispatch_worker
            NOLOGIN NOINHERIT BYPASSRLS
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'akc_deletion_worker') THEN
        CREATE ROLE akc_deletion_worker
            NOLOGIN NOINHERIT BYPASSRLS
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'akc_analysis_worker'
    ) THEN
        CREATE ROLE akc_analysis_worker
            NOLOGIN NOINHERIT BYPASSRLS
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'akc_url_fetcher'
    ) THEN
        CREATE ROLE akc_url_fetcher
            NOLOGIN NOINHERIT BYPASSRLS
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'akc_scheduler_runtime'
    ) THEN
        CREATE ROLE akc_scheduler_runtime
            LOGIN NOINHERIT
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
            PASSWORD 'akc_scheduler_dev_only_change_me';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'akc_dispatch_runtime'
    ) THEN
        CREATE ROLE akc_dispatch_runtime
            LOGIN NOINHERIT
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
            PASSWORD 'akc_dispatch_dev_only_change_me';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'akc_analysis_runtime'
    ) THEN
        CREATE ROLE akc_analysis_runtime
            LOGIN NOINHERIT
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
            PASSWORD 'akc_analysis_dev_only_change_me';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'akc_url_fetcher_runtime'
    ) THEN
        CREATE ROLE akc_url_fetcher_runtime
            LOGIN NOINHERIT
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
            PASSWORD 'akc_url_fetcher_dev_only_change_me';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'akc_deletion_runtime'
    ) THEN
        CREATE ROLE akc_deletion_runtime
            LOGIN NOINHERIT
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
            PASSWORD 'akc_deletion_dev_only_change_me';
    END IF;
END
$$;

GRANT akc_scheduler TO akc_scheduler_runtime;
GRANT akc_dispatch_worker TO akc_dispatch_runtime;
GRANT akc_analysis_worker TO akc_analysis_runtime;
GRANT akc_url_fetcher TO akc_url_fetcher_runtime;
GRANT akc_deletion_worker TO akc_deletion_runtime;
