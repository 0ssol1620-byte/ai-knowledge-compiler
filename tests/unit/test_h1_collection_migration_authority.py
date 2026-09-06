"""H1 G0B guard for collection migration authority.

L1 may add adapters and read paths, but it must not introduce a second migration
lineage that recreates the collection control-plane tables already owned by
0023_v4_collections and its descendants.
"""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
VERSIONS = REPOSITORY / "migrations" / "versions"

REVISION = re.compile(r'^revision(?:\s*:\s*str)?\s*=\s*["\']([^"\']+)["\']', re.M)
DOWN_REVISION = re.compile(
    r'^down_revision(?:\s*:\s*[^=]+?)?\s*=\s*(?:None|["\']([^"\']+)["\'])', re.M
)


def _identity(filename: str) -> tuple[str, str | None]:
    text = (VERSIONS / filename).read_text(encoding="utf-8")
    revision = REVISION.search(text)
    down = DOWN_REVISION.search(text)
    assert revision is not None, f"{filename} has no revision"
    assert down is not None, f"{filename} has no down_revision"
    return revision.group(1), down.group(1)


def test_collection_schema_has_one_authoritative_entry_revision() -> None:
    revision, parent = _identity("0023_v4_collections.py")
    assert revision == "0023_v4_collections"
    assert parent == "0023_trial_ingest"


def test_collection_follow_on_descends_from_authoritative_revision() -> None:
    revision, parent = _identity("0024_production_hybrid_retrieval.py")
    assert revision == "0024_production_hybrid_retrieval"
    assert parent == "0023_v4_collections"


def test_l1_duplicate_collection_schema_migration_is_not_promoted() -> None:
    assert not (VERSIONS / "0024_collection_discovery_slice.py").exists(), (
        "L1's discovery migration is a competing schema lineage: its behavior must "
        "be reconciled onto 0023_v4_collections rather than promoted as a second "
        "creator of collections/collection_events"
    )
