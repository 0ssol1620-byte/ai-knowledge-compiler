"""Deterministic benchmark sharding that never splits a document group."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .contracts import ContractError, canonical_sha256, require_sha256


@dataclass(frozen=True, slots=True, order=True)
class PageManifestEntry:
    document_id: str
    page_number: int
    page_id: str
    source_sha256: str
    estimated_seconds: float = 1.0
    page_class: str = "unknown"

    def __post_init__(self) -> None:
        if not self.document_id.strip() or not self.page_id.strip():
            raise ContractError("document_id and page_id are required")
        if self.page_number < 1:
            raise ContractError("page_number is one-based and must be positive")
        require_sha256(self.source_sha256, "source_sha256")
        if self.estimated_seconds <= 0:
            raise ContractError("estimated_seconds must be positive")
        if not self.page_class.strip():
            raise ContractError("page_class must be non-empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "page_id": self.page_id,
            "page_number": self.page_number,
            "source_sha256": self.source_sha256,
            "estimated_seconds": self.estimated_seconds,
            "page_class": self.page_class,
        }


@dataclass(frozen=True, slots=True)
class Shard:
    shard_id: str
    shard_index: int
    shard_count: int
    pages: tuple[PageManifestEntry, ...]
    estimated_seconds: float
    manifest_sha256: str

    @property
    def document_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(page.document_id for page in self.pages))

    def to_dict(self) -> dict[str, object]:
        return {
            "shard_id": self.shard_id,
            "shard_index": self.shard_index,
            "shard_count": self.shard_count,
            "pages": [page.to_dict() for page in self.pages],
            "estimated_seconds": self.estimated_seconds,
            "manifest_sha256": self.manifest_sha256,
        }


def _normalize_entries(entries: Iterable[PageManifestEntry]) -> tuple[PageManifestEntry, ...]:
    pages = tuple(
        sorted(entries, key=lambda page: (page.document_id, page.page_number, page.page_id))
    )
    if not pages:
        raise ContractError("benchmark page manifest may not be empty")
    page_ids: set[str] = set()
    document_pages: set[tuple[str, int]] = set()
    for page in pages:
        if page.page_id in page_ids:
            raise ContractError(f"duplicate page_id: {page.page_id}")
        key = (page.document_id, page.page_number)
        if key in document_pages:
            raise ContractError(f"duplicate document page coordinate: {key}")
        page_ids.add(page.page_id)
        document_pages.add(key)
    return pages


def _document_owner(document_id: str, shard_count: int, namespace: str) -> int:
    digest = hashlib.sha256(f"{namespace}\0{document_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % shard_count


def plan_document_shards(
    entries: Iterable[PageManifestEntry],
    *,
    shard_count: int,
    namespace: str,
) -> tuple[Shard, ...]:
    """Plan stable shards while assigning every page of a document together.

    Hashing the document identity is the group-preserving equivalent of the
    masterplan's ``hash(page_id) mod shard_count`` rule.  Input order, process
    count, and Python hash randomization cannot affect the result.
    """

    if shard_count < 1:
        raise ContractError("shard_count must be positive")
    if not namespace.strip():
        raise ContractError("a dataset/revision namespace is required")
    pages = _normalize_entries(entries)
    buckets: list[list[PageManifestEntry]] = [[] for _ in range(shard_count)]
    for page in pages:
        buckets[_document_owner(page.document_id, shard_count, namespace)].append(page)

    shards: list[Shard] = []
    for shard_index, bucket in enumerate(buckets):
        ordered = tuple(
            sorted(bucket, key=lambda page: (page.document_id, page.page_number, page.page_id))
        )
        bare_manifest = {
            "schema_version": "6.0.0",
            "namespace": namespace,
            "shard_index": shard_index,
            "shard_count": shard_count,
            "pages": [page.to_dict() for page in ordered],
        }
        manifest_sha256 = canonical_sha256(bare_manifest)
        shards.append(
            Shard(
                shard_id=f"shard-{shard_index + 1:04d}-of-{shard_count:04d}",
                shard_index=shard_index,
                shard_count=shard_count,
                pages=ordered,
                estimated_seconds=sum(page.estimated_seconds for page in ordered),
                manifest_sha256=manifest_sha256,
            )
        )
    validate_shard_plan(pages, shards, namespace=namespace)
    return tuple(shards)


def validate_shard_plan(
    entries: Iterable[PageManifestEntry],
    shards: Sequence[Shard],
    *,
    namespace: str,
) -> dict[str, object]:
    pages = _normalize_entries(entries)
    if not shards:
        raise ContractError("shard plan may not be empty")
    expected_count = len(shards)
    if {shard.shard_index for shard in shards} != set(range(expected_count)):
        raise ContractError("shard indexes must be complete and unique")
    if any(shard.shard_count != expected_count for shard in shards):
        raise ContractError("every shard must declare the same shard_count")

    actual_pages = [page for shard in shards for page in shard.pages]
    expected_by_id = {page.page_id: page for page in pages}
    actual_by_id: dict[str, PageManifestEntry] = {}
    for page in actual_pages:
        if page.page_id in actual_by_id:
            raise ContractError(f"page accepted by multiple shards: {page.page_id}")
        actual_by_id[page.page_id] = page
    if actual_by_id != expected_by_id:
        missing = sorted(expected_by_id.keys() - actual_by_id.keys())
        unexpected = sorted(actual_by_id.keys() - expected_by_id.keys())
        raise ContractError(f"shard coverage mismatch; missing={missing}, unexpected={unexpected}")

    owner_by_document: dict[str, int] = {}
    for shard in shards:
        expected_order = tuple(
            sorted(shard.pages, key=lambda page: (page.document_id, page.page_number, page.page_id))
        )
        if shard.pages != expected_order:
            raise ContractError(f"{shard.shard_id} page order is not canonical")
        expected_manifest = canonical_sha256(
            {
                "schema_version": "6.0.0",
                "namespace": namespace,
                "shard_index": shard.shard_index,
                "shard_count": shard.shard_count,
                "pages": [page.to_dict() for page in shard.pages],
            }
        )
        if shard.manifest_sha256 != expected_manifest:
            raise ContractError(f"{shard.shard_id} manifest digest mismatch")
        for document_id in shard.document_ids:
            previous = owner_by_document.setdefault(document_id, shard.shard_index)
            if previous != shard.shard_index:
                raise ContractError(f"document group split across shards: {document_id}")
            if shard.shard_index != _document_owner(document_id, expected_count, namespace):
                raise ContractError(
                    f"document assigned to a non-deterministic owner: {document_id}"
                )

    return {
        "gate": "MP0",
        "passed": True,
        "page_count": len(pages),
        "document_count": len(owner_by_document),
        "shard_count": expected_count,
        "no_page_loss": True,
        "document_context_preserved": True,
        "plan_sha256": canonical_sha256([shard.to_dict() for shard in shards]),
    }
