"""The v3 initial compile: a world built from sources, not from a fixture.

The revision path could always be driven end to end, but the world it revised
had to be handed to it. Every proof of the chain therefore began one step after
the beginning, and the first claim -- "v1 compile" -- was carried by a test
helper rather than by a compile. This is that step.

    real source resolution
      -> canonical units
      -> source provenance
      -> artifact graph
      -> collection projections
      -> candidate World v1
      -> receipt

Three things it deliberately does not do.

**It does not replace the production `initial_compile`.** That path is
`core-runtime-v2.ts` against the deployed Core, it has its own request envelope
and its own signature, and this shares neither. A new route was added instead of
a flag, because the change that breaks a working compile path is the one that
made it conditional.

**It does not promote.** `candidatePromotion` is `False` on the way out, exactly
as the revision path seals it. A compile that could activate its own result would
make the review gate advisory.

**It does not paper over an unresolved source fact.** A collection whose OCR
cannot ground an answer compiles to `review_required` with the fact named. The
alternative -- dropping the document and reporting success on the rest -- is the
failure this whole state machine exists to make impossible.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol

from akc_cir.revision_compile import (
    FAIL_CLOSED_SOURCE_FACT_STATES,
    PriorWorld,
    SourceFactState,
    audit_source_facts,
)

from .contract import canonicalize, digest
from .projections import COLLECTION_PROJECTIONS, ArtifactPlan, plan_artifacts
from .sources import (
    ObjectStore,
    ResolvedSource,
    SourceResolutionRefused,
    document_shape,
    resolve_sources,
)
from .wire import (
    RESPONSE_SCHEMA,
    RUNTIME,
    CompileRefused,
    check_release_digest,
    require,
    verify_envelope,
)

__all__ = [
    "InitialCompileResult",
    "InitialCompileService",
    "WorldArchiveWriter",
    "compile_initial",
]

INITIAL_SCHEMA = "tavonel.core_v3.initial_compile.v1"


class WorldArchiveWriter(Protocol):
    """The half of the archive this service uses: record a world it sealed."""

    def put(self, world: PriorWorld) -> None: ...


@dataclass(frozen=True, slots=True)
class InitialCompileResult:
    """World v1, and everything needed to check that it is what it says."""

    compile_id: str
    source_id: str
    resolved: ResolvedSource
    plan: ArtifactPlan
    state: Mapping[str, str]
    manifest_digest: str
    world_state_id: str
    lifecycle: str
    review_reasons: tuple[str, ...]

    def prior_world(self) -> PriorWorld:
        """The v1 side of the next revision, in the shape the compiler wants.

        Produced here rather than reassembled by the caller: the manifest digest,
        the artifact digests, the units and the shape all have to be the ones
        this compile sealed, and a caller rebuilding them from the response is a
        caller who can rebuild them slightly differently.
        """
        return PriorWorld(
            world_state_id=self.world_state_id,
            manifest_digest=self.manifest_digest,
            artifact_digests=dict(self.state),
            source_sha256=self.resolved.source_sha256,
            units=self.resolved.snapshots,
            shape=document_shape(self.resolved.units),
        )


def _collection_source_id(tenant_id: str, collection_id: str, source_sha256: str) -> str:
    seed = f"{tenant_id}\n{collection_id}\n{source_sha256}"
    return "src_" + sha256(seed.encode("utf-8")).hexdigest()[:32]


def compile_initial(
    *,
    tenant_id: str,
    collection_id: str,
    documents: Sequence[Mapping[str, Any]],
    store: ObjectStore,
) -> InitialCompileResult:
    """Resolve the sources and build every artifact of the first world."""
    resolved = resolve_sources(store, documents)
    plan = plan_artifacts(resolved)
    state = plan.full_rebuild()

    audit = audit_source_facts(resolved.facts)
    reasons: list[str] = []
    if audit.fail_closed:
        reasons.append(
            "source facts are unresolved or unrepresented: " + ", ".join(audit.fail_closed)
        )
    lifecycle = "review_required" if reasons else "candidate"

    # The manifest is a digest over the artifact digests plus the source binding,
    # so a world cannot be confused with one built from different documents that
    # happened to produce identical files.
    manifest_digest = digest(
        canonicalize(
            {
                "schema": INITIAL_SCHEMA,
                "collectionId": collection_id,
                "sourceSha256": resolved.source_sha256,
                "artifacts": dict(state),
            }
        )
    )
    compile_id = digest(
        canonicalize({"manifest": manifest_digest, "documents": len(resolved.documents)})
    )
    return InitialCompileResult(
        compile_id=compile_id,
        source_id=_collection_source_id(tenant_id, collection_id, resolved.source_sha256),
        resolved=resolved,
        plan=plan,
        state=state,
        manifest_digest=manifest_digest,
        world_state_id="world-" + manifest_digest.split(":", 1)[1][:24],
        lifecycle=lifecycle,
        review_reasons=tuple(reasons),
    )


class InitialCompileService:
    """The `initial_compile` operation class, on its own route.

    It takes the same signed envelope as the revision path and the same release
    digest, and it refuses a `revision_compile` request for the same reason the
    revision route refuses this one: an operation class that can be satisfied by
    either endpoint is an operation class that carries no information.
    """

    def __init__(
        self,
        *,
        hmac_secret: str,
        store: ObjectStore,
        core_release_digest: str,
        archive: WorldArchiveWriter | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        require(len(hmac_secret) >= 32, "CORE_V3_HMAC_SECRET_TOO_SHORT", 500)
        check_release_digest(core_release_digest)
        self._secret = hmac_secret.encode("utf-8")
        self._store = store
        self._release = core_release_digest
        #: Where a sealed world is recorded so a later revision can be compiled
        #: against it. The revision path needs the prior world's *units and
        #: shape*, which are not in any request and cannot be derived from one;
        #: writing them here, at the moment they are sealed, is what makes the
        #: two services compose without a caller carrying compiler state around.
        self._archive = archive
        if now is None:
            import time

            now = time.time
        self._now = now

    def verify(self, headers: Mapping[str, str], body: bytes) -> Mapping[str, Any]:
        request = verify_envelope(
            secret=self._secret,
            now=self._now,
            headers=headers,
            body=body,
            operation_class="initial_compile",
        )
        require(request.get("collectionId"), "CORE_V3_COLLECTION_ID_MISSING")
        # An initial compile has no predecessor. A request that names one is
        # either a revision sent to the wrong route or a caller who believes this
        # world has a parent, and both are worth refusing loudly.
        require("previousWorld" not in request, "CORE_V3_INITIAL_HAS_NO_PREDECESSOR")
        require("priorArtifactBindings" not in request, "CORE_V3_INITIAL_HAS_NO_PREDECESSOR")
        documents = request.get("documents") or {}
        require(isinstance(documents.get("initial"), list), "CORE_V3_DOCUMENTS_INVALID")
        require(documents["initial"], "CORE_V3_NO_SOURCE_DOCUMENT")
        return request

    def handle(self, headers: Mapping[str, str], body: bytes) -> tuple[int, dict[str, Any]]:
        try:
            request = self.verify(headers, body)
        except CompileRefused as refusal:
            return refusal.status, {"code": refusal.code}
        try:
            result = compile_initial(
                tenant_id=str(request.get("tenantId", "")),
                collection_id=str(request["collectionId"]),
                documents=request["documents"]["initial"],
                store=self._store,
            )
        except SourceResolutionRefused as refusal:
            return refusal.status, {"code": refusal.code}
        except CompileRefused as refusal:
            return refusal.status, {"code": refusal.code}
        if self._archive is not None:
            self._archive.put(result.prior_world())
        payload = self._seal(request, body, result)
        return (200 if payload["status"] != "rejected" else 422), payload

    def _seal(
        self, request: Mapping[str, Any], body: bytes, result: InitialCompileResult
    ) -> dict[str, Any]:
        compile_body = _initial_body(result)
        status = "completed" if result.lifecycle == "candidate" else "review_required"
        return {
            "schemaVersion": RESPONSE_SCHEMA,
            "status": status,
            "runtime": RUNTIME,
            "candidate": {
                "worldStateId": result.world_state_id,
                "parentWorldStateId": None,
                "manifestDigest": result.manifest_digest,
                "lifecycle": result.lifecycle,
                "reviewReasons": list(result.review_reasons),
            },
            "initial": compile_body,
            "receipt": {
                "requestId": request["requestId"],
                "inputSha256": "sha256:" + sha256(body).hexdigest(),
                "outputSha256": digest(canonicalize(compile_body)),
                "coreReleaseDigest": self._release,
                "matchingPolicy": "legacy",
                "candidatePromotion": False,
            },
        }


def _initial_body(result: InitialCompileResult) -> dict[str, Any]:
    facts = result.resolved.facts
    tally = audit_source_facts(facts)
    plan = result.plan
    projections = [artifact for artifact in COLLECTION_PROJECTIONS if artifact in result.state]
    return {
        "schema": INITIAL_SCHEMA,
        "compileId": result.compile_id,
        "sourceId": result.source_id,
        "sourceSha256": result.resolved.source_sha256,
        "documents": [
            {
                "documentId": document.document_id,
                "title": document.title,
                "pageCount": document.page_count,
                "inputSha256": document.input_sha256,
                "sourceImmutableKey": document.source_immutable_key,
            }
            for document in result.resolved.documents
        ],
        "units": [
            {
                "logicalUnitId": unit.logical_id,
                "documentId": unit.document_id,
                "section": unit.section,
                "explicitIdentifier": unit.explicit_identifier,
                "authority": unit.authority,
                "provenance": unit.provenance(),
            }
            for unit in result.resolved.units
        ],
        "artifacts": {
            "totalArtifacts": len(plan.artifacts),
            "artifactIds": list(plan.artifacts),
            "digests": dict(result.state),
            "bodies": plan.bodies(),
            "sensitivity": {a: list(plan.sensitivity[a]) for a in plan.artifacts},
        },
        # Named separately from `artifacts` so a caller can find the reserved
        # projections without knowing the prefix, while they remain ordinary
        # members of the same digest map above.
        "collectionProjections": projections,
        "sourceFacts": {
            "coveragePermille": round(tally.coverage * 1000),
            "sourceFaithful": tally.source_faithful,
            "failClosed": list(tally.fail_closed),
            "tally": {
                state.value: tally.tally.get(state.value, 0)
                for state in SourceFactState
            },
            "failClosedStates": sorted(state.value for state in FAIL_CLOSED_SOURCE_FACT_STATES),
        },
        "witnesses": result.resolved.witnesses(),
        "factCount": len(facts),
    }
