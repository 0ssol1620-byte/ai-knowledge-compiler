"""Command-line entrypoint for the durable URL-ingestion worker."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from typing import BinaryIO, cast

from akc_api.malware import malware_scanner_ready, scan_quarantined_stream
from akc_api.settings import Settings
from akc_api.storage import ObjectStoreSettings, build_object_store
from akc_telemetry import start_metrics_http_server

from akc_url_fetcher.database import (
    create_url_fetcher_engine,
    verify_url_fetcher_database,
)
from akc_url_fetcher.fetcher import FetchPolicy, SecureUrlFetcher
from akc_url_fetcher.security import UrlSecretCodec
from akc_url_fetcher.settings import UrlFetcherSettings
from akc_url_fetcher.worker import ScanResult, UrlFetchRuntime, UrlFetchWorker


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--check", action="store_true")
    return parser.parse_args()


async def _run(*, once: bool, check: bool) -> None:
    settings = UrlFetcherSettings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    engine = create_url_fetcher_engine(settings)
    try:
        await verify_url_fetcher_database(engine, settings)
        if settings.clamav_enabled and not await malware_scanner_ready(cast(Settings, settings)):
            raise RuntimeError("url_fetcher_clamav_unavailable")
        if check:
            return
        store = build_object_store(cast(ObjectStoreSettings, settings))
        codec = UrlSecretCodec(
            encryption_key=settings.effective_url_encryption_key,
            query_hmac_secret=settings.effective_url_query_hmac_secret,
        )

        async def scanner(stream: BinaryIO) -> ScanResult:
            return cast(
                ScanResult,
                await scan_quarantined_stream(
                    stream,
                    cast(Settings, settings),
                ),
            )

        fetcher = SecureUrlFetcher(
            FetchPolicy(
                max_bytes=settings.url_fetch_max_bytes,
                connect_timeout_seconds=settings.url_fetch_connect_timeout_seconds,
                read_timeout_seconds=settings.url_fetch_read_timeout_seconds,
                total_timeout_seconds=settings.url_fetch_total_timeout_seconds,
                max_redirects=settings.url_fetch_max_redirects,
                allowed_ports=frozenset({443}),
            )
        )
        worker = UrlFetchWorker(
            engine=engine,
            store=store,
            codec=codec,
            scanner=scanner,
            runtime=UrlFetchRuntime.from_settings(settings),
            fetcher=fetcher,
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
        await engine.dispose()


def main() -> None:
    args = _arguments()
    asyncio.run(_run(once=args.once, check=args.check))


if __name__ == "__main__":
    main()
