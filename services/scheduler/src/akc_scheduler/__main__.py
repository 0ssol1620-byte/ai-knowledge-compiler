"""Command-line entrypoint for the durable scheduler."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from akc_api.gpu_provider import RunpodGpuClient
from akc_api.storage import build_object_store
from akc_telemetry import set_provider_up, start_metrics_http_server
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from akc_scheduler.database import (
    create_deletion_engine,
    create_dispatch_engine,
    create_gpu_engine,
    create_scheduler_engine,
    verify_deletion_database,
    verify_dispatch_database,
    verify_gpu_database,
    verify_scheduler_database,
)
from akc_scheduler.deletions import DeletionWorker
from akc_scheduler.gpu_jobs import GpuInvocationWorker, GpuWorkerPolicy
from akc_scheduler.scheduler import DurableScheduler
from akc_scheduler.settings import SchedulerSettings
from akc_scheduler.telemetry import (
    refresh_scheduler_metrics,
    run_scheduler_metrics_loop,
)
from akc_scheduler.webhooks import HostAllowlist, WebhookHttpClient


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--once",
        action="store_true",
        help="process one bounded outbox and webhook batch, then exit",
    )
    modes.add_argument(
        "--check",
        action="store_true",
        help="validate configuration and database connectivity without mutation",
    )
    parser.add_argument(
        "--mode",
        choices=("all", "dispatch", "webhook", "deletion", "gpu"),
        default="all",
        help=("run only one production trust boundary; 'all' is restricted to development/test"),
    )
    return parser.parse_args()



async def _sweep_trial_sessions(
    sessions: async_sessionmaker[AsyncSession],
) -> int:
    """Retire expired anonymous trial sessions — ADR-006.

    Imported lazily and guarded: the scheduler must keep running its other
    duties even where the API package is unavailable or the capability was
    never deployed. A failure here is logged, not fatal — the sweep is
    idempotent and the next pass retries.
    """
    try:
        from akc_api.trial_retention import sweep_expired_trial_sessions
    except ImportError:
        return 0
    try:
        async with sessions() as session:
            return await sweep_expired_trial_sessions(session)
    except Exception:
        logging.getLogger(__name__).exception("trial retention sweep failed")
        return 0

async def _run(*, once: bool, check: bool, mode: str) -> None:
    settings = SchedulerSettings()
    if settings.env == "production" and mode == "all":
        raise RuntimeError("production_scheduler_mode_all_forbidden")
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    webhook_enabled = mode in {"all", "webhook"}
    dispatch_enabled = mode in {"all", "dispatch"}
    deletion_enabled = mode in {"all", "deletion"}
    gpu_enabled = mode == "gpu" or (mode == "all" and settings.gpu_worker_enabled)
    webhook_engine = create_scheduler_engine(settings) if webhook_enabled else None
    dispatch_engine = create_dispatch_engine(settings) if dispatch_enabled else None
    deletion_engine = create_deletion_engine(settings) if deletion_enabled else None
    gpu_engine = create_gpu_engine(settings) if gpu_enabled else None
    primary_engine = webhook_engine or dispatch_engine or deletion_engine or gpu_engine
    assert primary_engine is not None
    if check:
        try:
            if webhook_engine is not None:
                HostAllowlist(settings.allowed_webhook_hosts)
                await verify_scheduler_database(webhook_engine, settings)
            if dispatch_engine is not None:
                settings.validate_knowledge_runtime()
                await verify_dispatch_database(dispatch_engine, settings)
            if deletion_engine is not None:
                settings.validate_deletion_storage()
                await verify_deletion_database(deletion_engine, settings)
            if gpu_engine is not None:
                settings.validate_gpu_runtime()
                await verify_gpu_database(gpu_engine, settings)
        finally:
            if gpu_engine is not None:
                await gpu_engine.dispose()
            if deletion_engine is not None:
                await deletion_engine.dispose()
            if dispatch_engine is not None:
                await dispatch_engine.dispose()
            if webhook_engine is not None:
                await webhook_engine.dispose()
        return

    try:
        if webhook_engine is not None:
            await verify_scheduler_database(webhook_engine, settings)
        if dispatch_engine is not None:
            settings.validate_knowledge_runtime()
            await verify_dispatch_database(dispatch_engine, settings)
            set_provider_up(
                settings.knowledge_provider,
                up=settings.knowledge_provider == "deterministic",
            )
        if deletion_engine is not None:
            settings.validate_deletion_storage()
            await verify_deletion_database(deletion_engine, settings)
        if gpu_engine is not None:
            settings.validate_gpu_runtime()
            await verify_gpu_database(gpu_engine, settings)
    except BaseException:
        if gpu_engine is not None:
            await gpu_engine.dispose()
        if deletion_engine is not None:
            await deletion_engine.dispose()
        if dispatch_engine is not None:
            await dispatch_engine.dispose()
        if webhook_engine is not None:
            await webhook_engine.dispose()
        raise

    metrics_server = (
        start_metrics_http_server(
            port=settings.metrics_port,
            addr=settings.metrics_bind_host,
        )
        if settings.metrics_enabled
        else None
    )
    sessions = async_sessionmaker(
        bind=primary_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    http_client = WebhookHttpClient(
        allowed_hosts=settings.allowed_webhook_hosts,
        connect_timeout_seconds=settings.webhook_connect_timeout_seconds,
        read_timeout_seconds=settings.webhook_read_timeout_seconds,
        max_retry_after_seconds=settings.webhook_max_retry_after_seconds,
        max_redirects=settings.webhook_max_redirects,
    )
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=http_client,
        settings=settings,
        dispatch_engine=dispatch_engine or primary_engine,
        object_store=build_object_store(settings) if dispatch_enabled else None,
    )
    deletion_worker = (
        DeletionWorker(
            engine=deletion_engine,
            object_store=build_object_store(settings),
            settings=settings,
        )
        if deletion_engine is not None
        else None
    )
    gpu_client = (
        RunpodGpuClient(
            api_key=settings.runpod_api_key.get_secret_value(),
            worker_hmac_secret=settings.gpu_worker_hmac_secret.get_secret_value().encode(),
            allowed_input_hosts=settings.allowed_gpu_input_hosts,
            allowed_output_hosts=settings.allowed_gpu_output_hosts,
            request_timeout_seconds=settings.gpu_provider_call_timeout_seconds,
        )
        if gpu_engine is not None
        else None
    )
    gpu_worker = (
        GpuInvocationWorker(
            engine=gpu_engine,
            client=gpu_client,
            object_store=build_object_store(settings),
            policy=GpuWorkerPolicy(
                lease_seconds=settings.gpu_lease_seconds,
                provider_call_timeout_seconds=settings.gpu_provider_call_timeout_seconds,
                provider_job_timeout_seconds=settings.gpu_provider_job_timeout_seconds,
                poll_interval_seconds=settings.gpu_poll_interval_seconds,
                presign_ttl_seconds=settings.gpu_presign_ttl_seconds,
                backoff_base_seconds=settings.gpu_backoff_base_seconds,
                backoff_max_seconds=settings.gpu_backoff_max_seconds,
                backoff_jitter_ratio=settings.gpu_backoff_jitter_ratio,
                max_cancel_attempts=settings.gpu_max_cancel_attempts,
                max_output_bytes=settings.gpu_max_output_bytes,
            ),
        )
        if gpu_engine is not None and gpu_client is not None
        else None
    )
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        scheduler.request_stop()
        if deletion_worker is not None:
            deletion_worker.request_stop()
        if gpu_worker is not None:
            gpu_worker.request_stop()

    if not once:
        for signal_number in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signal_number, request_stop)
            except NotImplementedError:
                signal.signal(
                    signal_number,
                    lambda _signum, _frame: loop.call_soon_threadsafe(request_stop),
                )

    try:
        if once:
            dispatched = published = delivered = 0
            retained = 0
            if dispatch_enabled or webhook_enabled:
                dispatched, published, delivered = await scheduler.run_once(
                    dispatch_enabled=dispatch_enabled,
                    webhook_enabled=webhook_enabled,
                )
            if webhook_enabled:
                retained = await scheduler.cleanup_retained_rows()
            deleted = await deletion_worker.run_batch() if deletion_worker is not None else 0
            gpu_processed = await gpu_worker.run_batch() if gpu_worker is not None else 0
            # ADR-006. The one-hour trial lifetime is the bound on anonymous
            # storage, so it has to be swept on the same pass as every other
            # retention duty rather than left to a cron nobody owns.
            trial_retired = await _sweep_trial_sessions(sessions)
            if settings.metrics_enabled and (dispatch_enabled or webhook_enabled):
                await refresh_scheduler_metrics(sessions, mode=mode)
            logging.getLogger(__name__).info(
                "scheduler pass complete: dispatch=%d outbox=%d deliveries=%d "
                "retention=%d deletion=%d gpu=%d trial=%d",
                dispatched,
                published,
                delivered,
                retained,
                deleted,
                gpu_processed,
                trial_retired,
            )
        else:
            if settings.metrics_enabled:
                async with asyncio.TaskGroup() as tasks:
                    if dispatch_enabled or webhook_enabled:
                        tasks.create_task(
                            scheduler.run(
                                dispatch_enabled=dispatch_enabled,
                                webhook_enabled=webhook_enabled,
                            ),
                            name="durable-scheduler",
                        )
                        tasks.create_task(
                            run_scheduler_metrics_loop(
                                sessions,
                                mode=mode,
                                stopping=lambda: scheduler.stopping,
                            ),
                            name="scheduler-metrics",
                        )
                    if deletion_worker is not None:
                        tasks.create_task(
                            deletion_worker.run(),
                            name="deletion-worker",
                        )
                    if gpu_worker is not None:
                        tasks.create_task(
                            gpu_worker.run(
                                poll_interval_seconds=settings.scheduler_poll_interval_seconds
                            ),
                            name="gpu-invocation-worker",
                        )
            else:
                async with asyncio.TaskGroup() as tasks:
                    if dispatch_enabled or webhook_enabled:
                        tasks.create_task(
                            scheduler.run(
                                dispatch_enabled=dispatch_enabled,
                                webhook_enabled=webhook_enabled,
                            )
                        )
                    if deletion_worker is not None:
                        tasks.create_task(deletion_worker.run())
                    if gpu_worker is not None:
                        tasks.create_task(
                            gpu_worker.run(
                                poll_interval_seconds=settings.scheduler_poll_interval_seconds
                            )
                        )
    finally:
        await http_client.aclose()
        if gpu_client is not None:
            await gpu_client.aclose()
        if metrics_server is not None:
            await asyncio.to_thread(metrics_server.shutdown)
        if dispatch_engine is not None:
            await dispatch_engine.dispose()
        if deletion_engine is not None:
            await deletion_engine.dispose()
        if gpu_engine is not None:
            await gpu_engine.dispose()
        if webhook_engine is not None:
            await webhook_engine.dispose()


def main() -> None:
    args = _arguments()
    asyncio.run(_run(once=args.once, check=args.check, mode=args.mode))


if __name__ == "__main__":
    main()
