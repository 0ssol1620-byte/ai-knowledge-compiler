"""The production `SourceResolver`: real storage in, compiler inputs out.

`service.py` takes a resolver because a compile service that reaches for a bucket
itself cannot be driven by a test. That was the right seam, and it left a real
gap: the only resolver that existed was the one the end-to-end test wrote for
itself, so nothing in the repository turned stored OCR into the units, graph,
artifacts, builders and witnesses the compiler wants. This is that resolver.

It is stateless with respect to the sources -- every document is re-read from
immutable storage and re-canonicalised on each request -- and stateful in exactly
one place: the prior world. A revision is defined by the world it revises, and
the compiler needs that world's *units and shape*, not just its digests. Those
are not in the request and cannot be derived from it, so they are looked up in a
`WorldArchive`: the record the Core sealed when it compiled that world.

The lookup is checked rather than trusted. The archived record must carry the
manifest digest the request names, and `RevisionService` independently refuses if
the resolver hands back a world that is not the one asked for. A resolver that
returned the newest world it had would otherwise compile a revision of something
the caller never read.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from akc_cir.revision_compile import PriorWorld

from .projections import plan_artifacts
from .service import SourceResolution
from .sources import ObjectStore, SourceResolutionRefused, document_shape, resolve_sources

__all__ = [
    "InMemoryWorldArchive",
    "ProductionSourceResolver",
    "WorldArchive",
    "production_resolver",
]


class WorldArchive(Protocol):
    """Where the Core finds a world it previously sealed."""

    def get(self, manifest_digest: str) -> PriorWorld | None: ...


class InMemoryWorldArchive:
    """A process-local archive of sealed worlds.

    Not a test double: a Core process that has just compiled World v1 has the
    record in hand, and this is where it puts it. A deployment that spans
    processes swaps in a durable implementation of the same protocol -- the
    resolver never learns which it has.

    `put` refuses to overwrite. A manifest digest is a content address, so two
    different worlds cannot share one; an attempt to replace an entry means
    something upstream is reusing a digest, and that is worth failing on rather
    than resolving in favour of whichever arrived last.
    """

    def __init__(self) -> None:
        self._worlds: dict[str, PriorWorld] = {}

    def put(self, world: PriorWorld) -> None:
        existing = self._worlds.get(world.manifest_digest)
        if existing is not None and existing != world:
            raise ValueError(f"manifest digest already archived: {world.manifest_digest}")
        self._worlds[world.manifest_digest] = world

    def get(self, manifest_digest: str) -> PriorWorld | None:
        return self._worlds.get(manifest_digest)


class ProductionSourceResolver:
    """Resolve a revision request into everything `compile_revision` needs."""

    def __init__(self, *, store: ObjectStore, archive: WorldArchive) -> None:
        self._store = store
        self._archive = archive

    def __call__(self, request: Mapping[str, Any]) -> SourceResolution:
        previous_ref = request.get("previousWorld") or {}
        manifest_digest = str(previous_ref.get("manifestDigest", ""))
        previous = self._archive.get(manifest_digest)
        if previous is None:
            # The world the request names is not one this Core sealed. Compiling
            # against a reconstruction would produce a receipt whose lineage
            # nobody can check, so it stops here with a code the client already
            # knows how to refuse.
            raise SourceResolutionRefused("CORE_V3_PRIOR_WORLD_NOT_RESOLVED", 409)
        if not previous.units:
            raise SourceResolutionRefused("CORE_V3_PRIOR_WORLD_HAS_NO_UNITS", 409)

        documents = _current_documents(request)
        resolved = resolve_sources(self._store, documents)
        plan = plan_artifacts(resolved)
        return SourceResolution(
            previous=previous,
            after_units=resolved.snapshots,
            after_shape=document_shape(resolved.units),
            after_sha256=resolved.source_sha256,
            source_id=str(request.get("collectionId") or "collection"),
            graph=plan.graph,
            artifacts=plan.artifacts,
            build=plan.build,
            full_rebuild=plan.full_rebuild,
            materialise=plan.body,
            source_facts=resolved.facts,
        )


def _current_documents(request: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    """Every document of the collection at the version this request compiles.

    Changed and unchanged together. A revision that resolved only the changed
    documents would produce a world containing one document, and the compiler
    would correctly report that everything else had been deleted -- which is a
    perfectly consistent answer to the wrong question.
    """
    documents = request.get("documents") or {}
    changed = documents.get("changed") or []
    unchanged = documents.get("unchanged") or []
    if not isinstance(changed, list) or not isinstance(unchanged, list):
        raise SourceResolutionRefused("CORE_V3_DOCUMENTS_INVALID", 400)
    return [*changed, *unchanged]


def production_resolver(
    *, store: ObjectStore, archive: WorldArchive
) -> Callable[[Mapping[str, Any]], SourceResolution]:
    return ProductionSourceResolver(store=store, archive=archive)
