"""Operator entry point for the staged collection metadata bridge backfill."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from typing import Literal, cast

from akc_api.collection_metadata import build_collection_metadata_codec
from akc_api.collection_metadata_backfill import CollectionMetadataBackfill
from akc_api.database import Database
from akc_api.settings import Settings


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill one tenant's collection metadata without logging plaintext.",
    )
    parser.add_argument("--tenant-id", required=True, type=uuid.UUID)
    parser.add_argument("--batch-size", type=int, default=200)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    return parser.parse_args()


async def _run(arguments: argparse.Namespace) -> int:
    settings = Settings()
    codec = build_collection_metadata_codec(settings)
    if codec is None:
        raise RuntimeError("AKC_COLLECTION_METADATA_ENCRYPTION_ENABLED must be true")
    mode: Literal["dry-run", "apply", "verify"] = (
        "apply" if arguments.apply else "verify" if arguments.verify else "dry-run"
    )
    database = Database(settings)
    try:
        report = await CollectionMetadataBackfill(
            engine=database.engine,
            codec=codec,
            batch_size=cast(int, arguments.batch_size),
        ).run(
            mode=mode,
            tenant_id=cast(uuid.UUID, arguments.tenant_id),
        )
        print(json.dumps(report.public_dict(), separators=(",", ":"), sort_keys=True))
        return 0 if report.finalization_ready or mode == "dry-run" else 2
    finally:
        await database.dispose()


def main() -> int:
    return asyncio.run(_run(_arguments()))


if __name__ == "__main__":
    raise SystemExit(main())
