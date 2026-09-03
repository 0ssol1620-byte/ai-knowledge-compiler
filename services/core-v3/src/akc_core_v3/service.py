"""The v3 revision-compile endpoint: verify, compile, seal, refuse.

The division of labour is deliberate and narrow. This module owns the wire: the
HMAC, the input digest, the request shape, the response shape and the output
seal. It does not own where units come from -- a `SourceResolver` supplies those,
because in production they come from object storage and in a test they come from
a fixture, and a service that reached for a bucket itself could not be driven by
the end-to-end test that has to prove the client and the compiler agree.

Every refusal is a named code. A Core that cannot answer says which check
stopped it, because "500" and "the identity layer abstained" are different
outcomes and a product that cannot tell them apart will retry the second one
forever.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from akc_cir.dependency import DependencyGraph
from akc_cir.revision_compile import (
    IdentityContinuity,
    PriorWorld,
    RevisionCompileResult,
    RevisionDisposition,
    SourceFact,
    compile_revision,
)
from akc_cir.semantic_diff import DocumentShape, UnitSnapshot

from .contract import canonicalize, digest

REQUEST_SCHEMA = "tavonel.product_core.compile_request.v3"
RESPONSE_SCHEMA = "tavonel.product_core.compile_response.v3"
RUNTIME = "tavonel-python-core-v2"

#: The signature covers these three, joined by newlines, exactly as the client
#: builds them in `dispatchProductCoreRevision`.
SIGNED_FIELDS = ("timestamp", "requestId", "inputSha256")

#: Requests older than this are refused whatever their signature says. A valid
#: signature on a replayed body is still a replay.
MAX_CLOCK_SKEW_SECONDS = 300


class RevisionRefused(RuntimeError):
    """A refusal with a code the Product can act on."""

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True, slots=True)
class SourceResolution:
    """Everything the compiler needs, resolved from the request by the caller.

    The service never invents any of this. If a resolver cannot produce a prior
    unit set for the world the request names, it raises rather than returning an
    empty one: an empty prior version makes every unit look new, which is a
    plausible-looking answer to a question nobody asked.
    """

    previous: PriorWorld
    after_units: Sequence[UnitSnapshot]
    after_shape: DocumentShape
    after_sha256: str
    source_id: str
    graph: DependencyGraph
    artifacts: Sequence[str]
    build: Callable[[str], str]
    full_rebuild: Callable[[], Mapping[str, str]] | None = None
    source_facts: Sequence[SourceFact] = field(default_factory=tuple)
    #: Returns the body of an artifact the compile rebuilt.
    #:
    #: Without this the response is digests all the way down, and a caller
    #: holding the previous world has no way to assemble the next one: it can
    #: carry forward what did not change, because it already has those bytes,
    #: and it has nothing at all for what did. Supplying the bodies here keeps
    #: the assembly digest-bound -- every body is checked against the digest the
    #: receipt seals -- instead of making the caller trust a second channel.
    materialise: Callable[[str], Any] | None = None


SourceResolver = Callable[[Mapping[str, Any]], SourceResolution]


def _require(condition: object, code: str, status: int = 400) -> None:
    if not condition:
        raise RevisionRefused(code, status)


class RevisionService:
    def __init__(
        self,
        *,
        hmac_secret: str,
        resolve: SourceResolver,
        core_release_digest: str,
        now: Callable[[], float] | None = None,
    ) -> None:
        _require(len(hmac_secret) >= 32, "CORE_V3_HMAC_SECRET_TOO_SHORT", 500)
        _require(
            core_release_digest.startswith("sha256:") and len(core_release_digest) == 71,
            "CORE_V3_RELEASE_DIGEST_INVALID",
            500,
        )
        self._secret = hmac_secret.encode("utf-8")
        self._resolve = resolve
        self._release = core_release_digest
        if now is None:
            import time

            now = time.time
        self._now = now

    # -- wire ---------------------------------------------------------------

    def verify(self, headers: Mapping[str, str], body: bytes) -> Mapping[str, Any]:
        lower = {key.lower(): value for key, value in headers.items()}
        timestamp = lower.get("x-tavonel-core-timestamp", "")
        request_id = lower.get("x-tavonel-core-request-id", "")
        input_sha256 = lower.get("x-tavonel-input-sha256", "")
        signature = lower.get("x-tavonel-core-signature", "")
        _require(timestamp.isdigit(), "CORE_V3_TIMESTAMP_INVALID", 401)
        _require(request_id, "CORE_V3_REQUEST_ID_MISSING", 401)
        _require(
            abs(self._now() - int(timestamp)) <= MAX_CLOCK_SKEW_SECONDS,
            "CORE_V3_TIMESTAMP_OUT_OF_WINDOW",
            401,
        )
        expected = "sha256:" + sha256(body).hexdigest()
        _require(
            hmac.compare_digest(input_sha256, expected),
            "CORE_V3_INPUT_DIGEST_MISMATCH",
            401,
        )
        expected_signature = hmac.new(
            self._secret,
            f"{timestamp}\n{request_id}\n{input_sha256}".encode(),
            sha256,
        ).hexdigest()
        _require(
            hmac.compare_digest(signature, expected_signature),
            "CORE_V3_SIGNATURE_INVALID",
            401,
        )
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RevisionRefused("CORE_V3_BODY_NOT_JSON", 400) from error
        _require(isinstance(parsed, dict), "CORE_V3_BODY_NOT_JSON")
        request: dict[str, Any] = parsed
        _require(request.get("schemaVersion") == REQUEST_SCHEMA, "CORE_V3_SCHEMA_UNSUPPORTED")
        _require(request.get("requestId") == request_id, "CORE_V3_REQUEST_ID_MISMATCH", 401)
        route = request.get("route") or {}
        _require(
            route.get("operationClass") == "revision_compile",
            "CORE_V3_OPERATION_CLASS_UNSUPPORTED",
        )
        previous = request.get("previousWorld") or {}
        _require(previous.get("worldStateId"), "CORE_V3_PRIOR_WORLD_MISSING")
        _require(previous.get("manifestDigest"), "CORE_V3_PRIOR_WORLD_MISSING")
        _require(previous.get("coreOutputSha256"), "CORE_V3_PRIOR_WORLD_MISSING")
        documents = request.get("documents") or {}
        _require(isinstance(documents.get("changed"), list), "CORE_V3_DOCUMENTS_INVALID")
        _require(isinstance(documents.get("unchanged"), list), "CORE_V3_DOCUMENTS_INVALID")
        _require(documents["changed"], "CORE_V3_NO_CHANGED_DOCUMENT")
        _require(
            isinstance(request.get("priorArtifactBindings"), list),
            "CORE_V3_PRIOR_ARTIFACTS_INVALID",
        )
        return request

    # -- compile ------------------------------------------------------------

    def handle(self, headers: Mapping[str, str], body: bytes) -> tuple[int, dict[str, Any]]:
        try:
            request = self.verify(headers, body)
        except RevisionRefused as refusal:
            return refusal.status, {"code": refusal.code}
        try:
            resolution = self._resolve(request)
        except RevisionRefused as refusal:
            return refusal.status, {"code": refusal.code}
        previous = resolution.previous
        _bind = request["previousWorld"]
        if (
            previous.world_state_id != _bind["worldStateId"]
            or previous.manifest_digest != _bind["manifestDigest"]
        ):
            # The resolver handed back a different world than the one asked for.
            # Compiling onto it would produce a receipt the client is required to
            # refuse, so it is refused here where the reason is still known.
            return 409, {"code": "CORE_V3_PRIOR_WORLD_NOT_RESOLVED"}

        result = compile_revision(
            source_id=resolution.source_id,
            previous=previous,
            after_units=resolution.after_units,
            after_shape=resolution.after_shape,
            after_sha256=resolution.after_sha256,
            graph=resolution.graph,
            artifacts=resolution.artifacts,
            build=resolution.build,
            source_facts=resolution.source_facts,
            full_rebuild=resolution.full_rebuild,
        )
        try:
            rebuilt_bodies = _materialise(resolution, result)
        except RevisionRefused as refusal:
            return refusal.status, {"code": refusal.code}
        payload = self._seal(request, body, result, rebuilt_bodies)
        status = 200 if payload["status"] != "rejected" else 422
        return status, payload

    def _seal(
        self,
        request: Mapping[str, Any],
        body: bytes,
        result: RevisionCompileResult,
        rebuilt_bodies: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        revision = _revision_body(result, rebuilt_bodies)
        # Status and lifecycle are derived from the disposition rather than set
        # beside it, so the two cannot drift apart into a response the client
        # refuses for a reason that has nothing to do with the compile.
        status, lifecycle = {
            RevisionDisposition.PROMOTABLE: ("completed", "candidate"),
            RevisionDisposition.REVIEW_REQUIRED: ("review_required", "review_required"),
            RevisionDisposition.REJECTED: ("rejected", "rejected"),
        }[result.disposition]
        world_state_id = "world-" + digest(revision["changeId"]).split(":", 1)[1][:24]
        return {
            "schemaVersion": RESPONSE_SCHEMA,
            "status": status,
            "runtime": RUNTIME,
            "candidate": {
                "worldStateId": world_state_id,
                "parentWorldStateId": result.previous_world_state_id,
                "manifestDigest": digest(canonicalize(result.state)),
                "lifecycle": lifecycle,
                "reviewReasons": list(result.review_reasons),
            },
            "revision": revision,
            "receipt": {
                "requestId": request["requestId"],
                "inputSha256": "sha256:" + sha256(body).hexdigest(),
                "outputSha256": digest(canonicalize(revision)),
                "coreReleaseDigest": self._release,
                "matchingPolicy": "legacy",
                "candidatePromotion": False,
            },
        }


def artifact_content(body: Any) -> str:
    """The bytes an artifact body stands for.

    A string body is the content itself. Half the package a caller assembles is
    CSV, JSON Lines and Turtle, and wrapping those in JSON quoting to force one
    convention would make the digest of a rebuilt file disagree with the digest
    of the file it replaces. Anything else is a document, and its content is its
    canonical form -- the same form the receipt is sealed over.
    """
    return body if isinstance(body, str) else canonicalize(body)


def _materialise(
    resolution: SourceResolution, result: RevisionCompileResult
) -> dict[str, Any] | None:
    """Collect the bodies of the rebuilt artifacts, and check each one.

    A body that does not hash to the digest the compile recorded is refused
    rather than sent. Shipping it would seal a receipt whose digests describe
    one set of bytes and whose bodies are another, and the caller would have no
    way to tell which half was wrong.
    """
    if resolution.materialise is None:
        return None
    bodies: dict[str, Any] = {}
    for artifact_id in result.rebuilt_artifact_ids:
        artifact_body = resolution.materialise(artifact_id)
        if digest(artifact_content(artifact_body)) != result.state[artifact_id]:
            raise RevisionRefused("CORE_V3_REBUILT_BODY_DIGEST_MISMATCH", 500)
        bodies[artifact_id] = artifact_body
    return bodies


def _revision_body(
    result: RevisionCompileResult, rebuilt_bodies: dict[str, Any] | None = None
) -> dict[str, Any]:
    units = [
        {
            "logicalUnitId": unit.logical_unit_id,
            "identityContinuity": unit.continuity.value,
            "changeState": unit.change_state.value,
            "changeStates": [state.value for state in unit.change_states],
            "identityFingerprint": unit.identity_fingerprint,
            "changeFingerprint": unit.change_fingerprint,
            **(
                {"previousLogicalUnitId": unit.previous_logical_unit_id}
                if unit.previous_logical_unit_id
                else {}
            ),
            **({"identityRelation": unit.relation.value} if unit.relation else {}),
            **(
                {"identityCandidates": list(unit.identity_candidates)}
                if unit.identity_candidates
                else {}
            ),
        }
        for unit in result.units
    ]
    typed: dict[str, int] = {}
    for unit in result.units:
        for state in unit.change_states:
            typed[state.value] = typed.get(state.value, 0) + 1
    carried = list(result.carried_forward_artifact_ids)
    audit = result.source_facts
    return {
        "changeId": result.change_id,
        "previousWorldStateId": result.previous_world_state_id,
        "previousManifestDigest": result.previous_manifest_digest,
        "identity": {
            "continued": sum(
                1 for u in result.units if u.continuity is IdentityContinuity.CONTINUED
            ),
            "new": sum(1 for u in result.units if u.continuity is IdentityContinuity.NEW),
            "ambiguous": sum(
                1 for u in result.units if u.continuity is IdentityContinuity.AMBIGUOUS
            ),
            "unresolved": sum(
                1 for u in result.units if u.continuity is IdentityContinuity.UNRESOLVED
            ),
            "units": units,
        },
        "typedChanges": typed,
        "impact": {
            "affectedArtifactIds": list(result.plan.stale),
            "unresolvedArtifactIds": list(result.plan.unresolved),
        },
        "recompilation": {
            "totalArtifacts": result.total_artifacts,
            "rebuiltArtifacts": len(result.rebuilt_artifact_ids),
            "workAvoidedArtifacts": result.work_avoided_artifacts,
            "rebuiltArtifactIds": list(result.rebuilt_artifact_ids),
            "carriedForwardArtifactIds": carried,
            "quarantinedArtifactIds": list(result.quarantined_artifact_ids),
            "carriedForwardDigests": {artifact: result.state[artifact] for artifact in carried},
            "rebuiltDigests": {
                artifact: result.state[artifact] for artifact in result.rebuilt_artifact_ids
            },
            # The bodies of what was rebuilt, when a resolver can produce them.
            # Named apart from `rebuiltArtifacts`, which is the count.
            **({"rebuiltArtifactBodies": rebuilt_bodies} if rebuilt_bodies is not None else {}),
        },
        "sourceFacts": {
            # Permille rather than a ratio: the digest refuses floats, and a
            # float here would make the Node client's recomputation disagree for
            # a reason that has nothing to do with the compile.
            "coveragePermille": round(audit.coverage * 1000),
            "sourceFaithful": audit.source_faithful,
            "failClosed": list(audit.fail_closed),
        },
        "unresolvedChannels": [state.value for state in result.unresolved_channels],
        "equivalence": result.equivalence,
        "disposition": result.disposition.value,
    }
