"""Command-line entrypoint for the durable CPU document worker."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from typing import cast

from akc_api.storage import ObjectStoreSettings, build_object_store
from akc_security import RedisPdfSecretStore
from akc_telemetry import start_metrics_http_server

from akc_worker_document.database import (
    create_analysis_engine,
    verify_analysis_database,
)
from akc_worker_document.settings import AnalysisWorkerSettings
from akc_worker_document.worker import (
    AnalysisRuntime,
    AnalysisWorker,
    verify_sandbox_launcher,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--check", action="store_true")
    return parser.parse_args()


async def _run(*, once: bool, check: bool) -> None:
    settings = AnalysisWorkerSettings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    engine = create_analysis_engine(settings)
    pdf_secret_store: RedisPdfSecretStore | None = None
    try:
        runtime = AnalysisRuntime.from_worker_settings(settings)
        await verify_sandbox_launcher(runtime)
        await verify_analysis_database(engine, settings)
        if check:
            return
        store = build_object_store(cast(ObjectStoreSettings, settings))
        if settings.redis_url:
            pdf_secret_store = RedisPdfSecretStore.from_url(
                settings.redis_url,
                encryption_key=settings.pdf_password_encryption_key or "",
                key_secret=settings.effective_pdf_password_key_secret,
            )
        worker = AnalysisWorker(
            engine=engine,
            store=store,
            runtime=runtime,
            pdf_secret_store=pdf_secret_store,
        )
        metrics_server = (
            start_metrics_http_server(
                port=settings.metrics_port,
                addr=settings.metrics_bind_host,
            )
            if settings.metrics_enabled
            else None
        )
        loop = asyncio.get_running_loop()
        if not once:
            for signal_number in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(signal_number, worker.request_stop)
                except NotImplementedError:
                    signal.signal(
                        signal_number,
                        lambda _signum, _frame: loop.call_soon_threadsafe(worker.request_stop),
                    )
        try:
            if once:
                await worker.run_once()
                if settings.metrics_enabled:
                    await worker.refresh_metrics()
            else:
                await worker.run()
        finally:
            if metrics_server is not None:
                await asyncio.to_thread(metrics_server.shutdown)
    finally:
        try:
            if pdf_secret_store is not None:
                await pdf_secret_store.close()
        finally:
            await engine.dispose()


def main() -> None:
    args = _arguments()
    asyncio.run(_run(once=args.once, check=args.check))


if __name__ == "__main__":
    main()
