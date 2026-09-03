"""The artifact graph, including the collection-level projections.

A collection's world is not only per-unit files. It also carries projections
*about* the collection -- the ontology, the directory plan, the retrieval index --
and until now the Core did not return them. The Product could not assemble a
promotable candidate as a result, and said so in
`COLLECTION_PROJECTIONS_NOT_RETURNED_BY_CORE` rather than filling the gap with
pre-revision content or a second compiler.

They are returned here, and the way they are returned matters more than the fact
of it. A projection is **an ordinary artifact under a reserved id**: it sits in
the same dependency graph, is rebuilt or carried forward by the same plan, and
its digest is sealed in the same receipt. Nothing special-cases it. If they were
instead appended to the response after the compile, they would be exactly the
untraceable content the refusal existed to prevent -- signed, but not accounted
for.

The consequence worth checking is that they are *not* all rebuilt every time.
`collection:directory` is sensitive to structure alone, so amending the text of a
clause leaves it carried forward with the digest the previous world sealed, while
`collection:ontology` rebuilds because a claim it projects has changed. A
projection that always rebuilt would pass a stale-escape test and quietly make
selective recompilation worthless for the largest files in the package.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from akc_cir.dependency import (
    DependencyChannel,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
)

from .contract import artifact_content, digest
from .sources import CanonicalUnit, ResolvedSource

__all__ = [
    "COLLECTION_PROJECTIONS",
    "DIRECTORY",
    "ONTOLOGY",
    "RESERVED_PREFIX",
    "RETRIEVAL_INDEX",
    "ArtifactPlan",
    "plan_artifacts",
]

#: Reserved namespace. A document-derived artifact may never take an id in it,
#: which is checked below rather than left as a convention.
RESERVED_PREFIX = "collection:"

ONTOLOGY = "collection:ontology"
DIRECTORY = "collection:directory"
RETRIEVAL_INDEX = "collection:retrieval-index"

#: Ordered as the package lists them, not by sensitivity, so the response is
#: readable next to the files it describes.
COLLECTION_PROJECTIONS: tuple[str, ...] = (DIRECTORY, ONTOLOGY, RETRIEVAL_INDEX)

#: What each artifact kind is sensitive to.
#:
#: These are the load-bearing lines of the module. A grounded chunk cites a page
#: and a box, so `retrieval:` goes stale when the evidence moves even if the
#: words are identical; a claim does not, so it does not. The directory plan is
#: a structural projection and is deliberately blind to wording -- which is what
#: lets it be carried forward across an amendment, and what would be wrong if it
#: also carried the claim text.
_SEMANTIC = frozenset({DependencyChannel.SEMANTIC})
_STRUCTURAL = frozenset({DependencyChannel.STRUCTURAL})
_GROUNDED = frozenset(
    {DependencyChannel.SEMANTIC, DependencyChannel.LOCATOR, DependencyChannel.VISUAL}
)
_SEMANTIC_STRUCTURAL = frozenset({DependencyChannel.SEMANTIC, DependencyChannel.STRUCTURAL})


def claim_id(unit: CanonicalUnit) -> str:
    return f"claim:{unit.logical_id}"


def retrieval_id(unit: CanonicalUnit) -> str:
    return f"retrieval:{unit.logical_id}"


def summary_id(document_id: str) -> str:
    return f"summary:{document_id}"


GRAPH_RELATIONS = "graph:relations"


@dataclass(frozen=True, slots=True)
class ArtifactPlan:
    """Every artifact of the world, the graph over them, and how to build one."""

    artifacts: tuple[str, ...]
    graph: DependencyGraph
    #: artifact id -> the channels it reads on, kept so the response can say why
    #: a projection was carried forward instead of leaving the Product to infer
    #: it from the absence of a rebuild.
    sensitivity: Mapping[str, tuple[str, ...]]
    _units: tuple[CanonicalUnit, ...]
    _reads: Mapping[str, tuple[str, ...]]

    def body(self, artifact_id: str) -> Any:
        return _body(artifact_id, self._units, self._reads)

    def build(self, artifact_id: str) -> str:
        return digest(artifact_content(self.body(artifact_id)))

    def full_rebuild(self) -> dict[str, str]:
        """An independent rebuild of everything, for the equivalence oracle."""
        return {artifact: self.build(artifact) for artifact in self.artifacts}

    def bodies(self) -> dict[str, Any]:
        return {artifact: self.body(artifact) for artifact in self.artifacts}


def _by_id(units: Sequence[CanonicalUnit]) -> dict[str, CanonicalUnit]:
    return {unit.logical_id: unit for unit in units}


def _body(
    artifact_id: str,
    units: Sequence[CanonicalUnit],
    reads: Mapping[str, tuple[str, ...]],
) -> Any:
    index = _by_id(units)
    members = [index[logical] for logical in reads[artifact_id] if logical in index]

    if artifact_id == DIRECTORY:
        # Structure only. No clause text appears here, which is precisely why it
        # survives an amendment: including a snippet "for readability" would make
        # every wording change rebuild the directory of every collection.
        documents: dict[str, dict[str, Any]] = {}
        for unit in members:
            entry = documents.setdefault(
                unit.document_id,
                {"documentId": unit.document_id, "title": unit.document_title, "sections": {}},
            )
            section = entry["sections"].setdefault(
                unit.section, {"heading": unit.section, "clauses": []}
            )
            section["clauses"].append(unit.explicit_identifier)
        return {
            "projection": DIRECTORY,
            "schema": "tavonel.collection_projection.directory.v1",
            "documents": [
                {
                    "documentId": entry["documentId"],
                    "title": entry["title"],
                    "sections": [
                        {"heading": s["heading"], "clauses": sorted(s["clauses"])}
                        for s in sorted(entry["sections"].values(), key=lambda x: x["heading"])
                    ],
                }
                for entry in sorted(documents.values(), key=lambda x: x["documentId"])
            ],
        }

    if artifact_id == ONTOLOGY:
        return {
            "projection": ONTOLOGY,
            "schema": "tavonel.collection_projection.ontology.v1",
            "concepts": [
                {
                    "conceptId": unit.logical_id,
                    "label": unit.section,
                    "clause": unit.explicit_identifier,
                    "statement": unit.text,
                    "authority": unit.authority,
                    "evidence": unit.provenance(),
                }
                for unit in members
            ],
        }

    if artifact_id == RETRIEVAL_INDEX:
        return {
            "projection": RETRIEVAL_INDEX,
            "schema": "tavonel.collection_projection.retrieval_index.v1",
            "chunks": [
                {
                    "chunkId": f"chunk:{unit.logical_id}",
                    "text": unit.text,
                    "provenance": unit.provenance(),
                }
                for unit in members
            ],
        }

    if artifact_id == GRAPH_RELATIONS:
        return {
            "artifact": artifact_id,
            "nodes": [
                {"id": unit.logical_id, "section": unit.section, "document": unit.document_id}
                for unit in members
            ],
        }

    # Per-unit and per-document artifacts share one shape: the text that answers,
    # and the witness that shows it. Page and box travel with the words, which is
    # what makes a wrong-version citation a detectable failure rather than a
    # cosmetic one.
    return {
        "artifact": artifact_id,
        "reads": [
            {
                "logicalId": unit.logical_id,
                "text": unit.text,
                "provenance": unit.provenance(),
            }
            for unit in members
        ],
    }


def plan_artifacts(resolved: ResolvedSource) -> ArtifactPlan:
    units = resolved.units
    reads: dict[str, tuple[str, ...]] = {}
    channels: dict[str, frozenset[DependencyChannel]] = {}

    for unit in units:
        if unit.logical_id.startswith(RESERVED_PREFIX):  # pragma: no cover - id shape forbids it
            raise ValueError(f"unit id enters the reserved projection namespace: {unit.logical_id}")
        reads[claim_id(unit)] = (unit.logical_id,)
        channels[claim_id(unit)] = _SEMANTIC
        reads[retrieval_id(unit)] = (unit.logical_id,)
        channels[retrieval_id(unit)] = _GROUNDED

    for document in resolved.documents:
        members = tuple(u.logical_id for u in units if u.document_id == document.document_id)
        if not members:
            continue
        reads[summary_id(document.document_id)] = members
        channels[summary_id(document.document_id)] = _SEMANTIC

    everything = tuple(unit.logical_id for unit in units)
    reads[GRAPH_RELATIONS] = everything
    channels[GRAPH_RELATIONS] = _SEMANTIC_STRUCTURAL
    reads[DIRECTORY] = everything
    channels[DIRECTORY] = _STRUCTURAL
    reads[ONTOLOGY] = everything
    channels[ONTOLOGY] = _SEMANTIC_STRUCTURAL
    reads[RETRIEVAL_INDEX] = everything
    channels[RETRIEVAL_INDEX] = _GROUNDED

    graph = DependencyGraph(
        [
            DependencyEdge(
                source_id=artifact,
                target_id=logical,
                edge_type=EdgeType.DERIVED_FROM,
                channels=channels[artifact],
            )
            for artifact, members in reads.items()
            for logical in members
        ]
    )
    artifacts = tuple(sorted(reads))
    return ArtifactPlan(
        artifacts=artifacts,
        graph=graph,
        sensitivity={
            artifact: tuple(sorted(channel.value for channel in channels[artifact]))
            for artifact in artifacts
        },
        _units=tuple(units),
        _reads=reads,
    )
