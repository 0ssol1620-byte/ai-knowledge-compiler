"""World v1, a source revision, World v2 -- over a real socket, end to end.

This is the scenario the product claim rests on, and it is run here rather than
described:

    Contract_v1.pdf is compiled, reviewed and activated as World v1.
    The payment clause is amended from 30 days to 45 days.
    Contract_v2.pdf is compiled against World v1.
    Only what reads that clause is rebuilt; everything else is carried forward.
    The result is compared against an independently written full rebuild.
    Every source fact is accounted for.
    A human activates World v2.
    Asking "What is the payment term?" answers 45 days, and the citation opens
    the page and box the amended clause occupies in v2 -- not in v1.

The compile half runs through `akc_core_v3.RevisionService` over HTTP on
loopback, signed exactly the way `dispatchProductCoreRevision` signs it in
`nextjs/lib/core-runtime-revision.ts`. Nothing here calls `compile_revision`
directly, because the thing being tested is the contract between two processes
and calling the function would skip it.

The response is written to a fixture that the Node client's cross-language test
validates with its real validator. That is what closes the loop: the bytes a
Python compiler sealed are accepted by the TypeScript client that has to refuse
anything it cannot account for, and the digest agreement between
`json.dumps(sort_keys=True)` and `canonicalizeRevision` is a result rather than
an assumption.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "core-v3" / "src"))

from akc_cir.dependency import (  # noqa: E402
    DependencyChannel,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
)
from akc_cir.revision_compile import (  # noqa: E402
    PriorWorld,
    SourceFact,
    SourceFactState,
)
from akc_cir.semantic_diff import DocumentShape, UnitSnapshot  # noqa: E402
from akc_core_v3.server import ROUTE, serve  # noqa: E402
from akc_core_v3.service import RevisionService, SourceResolution  # noqa: E402

HMAC_SECRET = "e2e-revision-secret-that-is-long-enough-32+"
CORE_RELEASE = "sha256:" + "e" * 64
FIXTURE = REPO / "docs/evidence/artifacts/revision-compile-e2e-v1.json"


# ---------------------------------------------------------------------------
# the contract, with the provenance an answer has to cite


@dataclass(frozen=True, slots=True)
class Clause:
    logical_id: str
    section: str
    anchor: str
    text: str
    page: int
    bbox1000: tuple[int, int, int, int]

    def snapshot(self) -> UnitSnapshot:
        return UnitSnapshot(
            logical_id=self.logical_id,
            text=self.text,
            document_path=("Contract", self.section),
            anchor=self.anchor,
            explicit_identifier=self.anchor,
            evidence_id=f"ev_{self.logical_id}_p{self.page}",
            page_number1=self.page,
        )


V1_CLAUSES = (
    Clause(
        "ku_payment",
        "4. Payment",
        "4.1",
        "Payment is due within 30 days of invoice.",
        2,
        (120, 340, 880, 372),
    ),
    Clause(
        "ku_law",
        "9. Governing law",
        "9.1",
        "This agreement is governed by the laws of the Republic of Korea.",
        4,
        (120, 210, 880, 242),
    ),
    Clause(
        "ku_address",
        "1. Parties",
        "1.2",
        "Registered office: 12 Sejong-daero, Jung-gu, Seoul.",
        1,
        (120, 560, 880, 592),
    ),
    Clause(
        "ku_signatories",
        "10. Signatures",
        "10.1",
        "Signed by the authorised representatives of both parties.",
        5,
        (120, 120, 880, 152),
    ),
)

# The amendment. The clause moves down the page as well as changing its words --
# a real re-typeset does both, and a locator change that travelled on the same
# channel as the meaning change would make the test easier than reality.
V2_CLAUSES = tuple(
    replace(
        clause,
        text="Payment is due within 45 days of invoice.",
        page=2,
        bbox1000=(120, 356, 880, 388),
    )
    if clause.logical_id == "ku_payment"
    else clause
    for clause in V1_CLAUSES
)

READS: dict[str, tuple[str, ...]] = {
    "claim:payment": ("ku_payment",),
    "claim:law": ("ku_law",),
    "claim:address": ("ku_address",),
    "claim:signatories": ("ku_signatories",),
    "summary:contract": ("ku_payment", "ku_law"),
    "retrieval:payment": ("ku_payment",),
    "graph:relations": ("ku_payment", "ku_law", "ku_address", "ku_signatories"),
}
ARTIFACTS = tuple(sorted(READS))


def _shape(clauses: tuple[Clause, ...]) -> DocumentShape:
    return DocumentShape(
        heading_path_set=frozenset(("Contract", c.section) for c in clauses),
        block_count=len(clauses),
        unit_order=tuple(c.logical_id for c in clauses),
    )


def _graph() -> DependencyGraph:
    return DependencyGraph(
        [
            DependencyEdge(
                source_id=artifact,
                target_id=unit,
                edge_type=EdgeType.DERIVED_FROM,
                channels=frozenset({DependencyChannel.SEMANTIC}),
            )
            for artifact, reads in READS.items()
            for unit in reads
        ]
    )


def _artifact_body(artifact: str, clauses: tuple[Clause, ...]) -> dict[str, object]:
    """The artifact's actual bytes, provenance included.

    Page and box travel with the text. That is what makes the last step of the
    scenario checkable: an answer that carries the right words and the previous
    version's coordinates is still wrong.
    """
    by_id = {clause.logical_id: clause for clause in clauses}
    return {
        "artifact": artifact,
        "reads": [
            {
                "logicalId": item,
                "text": by_id[item].text,
                "provenance": {
                    "evidenceId": f"ev_{item}_p{by_id[item].page}",
                    "pageNumber1": by_id[item].page,
                    "bbox1000": list(by_id[item].bbox1000),
                },
            }
            for item in READS[artifact]
        ],
    }


def _digest_of(body: dict[str, object]) -> str:
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class Workspace:
    """Holds the bytes. The compiler's contract is digests; somebody keeps content."""

    def __init__(self) -> None:
        self.bodies: dict[str, dict[str, object]] = {}
        self.built: list[str] = []

    def full_build(self, clauses: tuple[Clause, ...]) -> dict[str, str]:
        out: dict[str, str] = {}
        for artifact in ARTIFACTS:
            body = _artifact_body(artifact, clauses)
            self.bodies[artifact] = body
            out[artifact] = _digest_of(body)
        return out

    def builder(self, clauses: tuple[Clause, ...]):
        def build(artifact: str) -> str:
            body = _artifact_body(artifact, clauses)
            self.bodies[artifact] = body
            self.built.append(artifact)
            return _digest_of(body)

        return build

    def oracle(self, clauses: tuple[Clause, ...]):
        """An independent full rebuild. Writes nothing into the workspace."""

        def full() -> dict[str, str]:
            return {
                artifact: _digest_of(_artifact_body(artifact, clauses)) for artifact in ARTIFACTS
            }

        return full


def _source_facts(clauses: tuple[Clause, ...]) -> list[SourceFact]:
    facts = [
        SourceFact(
            fact_id=f"sf-content-{clause.logical_id}",
            kind="CONTENT_TEXT",
            state=SourceFactState.REPRESENTED,
            logical_id=clause.logical_id,
        )
        for clause in clauses
    ]
    facts += [
        SourceFact(
            fact_id=f"sf-span-{clause.logical_id}",
            kind="PROVENANCE_SPAN",
            state=SourceFactState.REPRESENTED,
            logical_id=clause.logical_id,
        )
        for clause in clauses
    ]
    facts.append(
        SourceFact(
            fact_id="sf-page-furniture",
            kind="ACCESSIBILITY",
            state=SourceFactState.IGNORED,
            policy_id="policy.page-furniture.out-of-scope.v1",
        )
    )
    return facts


# ---------------------------------------------------------------------------
# the service, and the client half of the wire


@pytest.fixture
def world_v1() -> tuple[Workspace, PriorWorld]:
    workspace = Workspace()
    digests = workspace.full_build(V1_CLAUSES)
    prior = PriorWorld(
        world_state_id="world-v1",
        manifest_digest=_digest_of({"world": "v1", "artifacts": digests}),
        artifact_digests=digests,
        source_sha256="sha256:" + "1" * 64,
        units=[clause.snapshot() for clause in V1_CLAUSES],
        shape=_shape(V1_CLAUSES),
    )
    return workspace, prior


def _resolver(workspace: Workspace, prior: PriorWorld, after: tuple[Clause, ...], *, facts=None):
    def resolve(request):
        return SourceResolution(
            previous=prior,
            after_units=[clause.snapshot() for clause in after],
            after_shape=_shape(after),
            after_sha256="sha256:" + "2" * 64,
            source_id="src_" + "c" * 32,
            graph=_graph(),
            artifacts=ARTIFACTS,
            build=workspace.builder(after),
            full_rebuild=workspace.oracle(after),
            source_facts=_source_facts(after) if facts is None else facts,
        )

    return resolve


@pytest.fixture
def endpoint(world_v1):
    workspace, prior = world_v1
    service = RevisionService(
        hmac_secret=HMAC_SECRET,
        resolve=_resolver(workspace, prior, V2_CLAUSES),
        core_release_digest=CORE_RELEASE,
    )
    httpd, stop = serve(service)
    try:
        yield httpd.server_address, workspace, prior
    finally:
        stop()


def _build_request(prior: PriorWorld) -> dict:
    """The request the Node client builds, field for field.

    Mirrored rather than imported, because the client is TypeScript. The
    cross-language fixture written at the end of this test is what stops the
    mirror from drifting: the Node validator checks that response against the
    request it would itself have produced.
    """
    changed = [
        {
            "nativeId": "doc-contract",
            "connectorType": "foundation-r2",
            "immutableObjectKey": "immutable/pilot/pilot/doc-contract/v2/sanitized.pdf",
            "ocrObjectKey": "immutable/pilot/pilot/doc-contract/v2/ocr.json",
            "contentSha256": "sha256:" + "2" * 64,
            "previousContentSha256": "sha256:" + "1" * 64,
            "title": "Supply agreement",
            "sourceFilename": "contract.pdf",
            "pageCount": 6,
        }
    ]
    unchanged: list[dict] = []
    prior_bindings = [
        {"artifactId": artifact, "contentSha256": prior.artifact_digests[artifact]}
        for artifact in sorted(prior.artifact_digests)
    ]
    binding = "\n".join(
        [
            prior.world_state_id,
            prior.manifest_digest,
            "sha256:" + "b" * 64,
            *[
                f"{item['nativeId']}:{item['previousContentSha256']}->{item['contentSha256']}"
                for item in changed
            ],
        ]
    )
    return {
        "schemaVersion": "tavonel.product_core.compile_request.v3",
        "requestId": "core-rev-e2e",
        "idempotencyKey": "revision-" + hashlib.sha256(binding.encode("utf-8")).hexdigest()[:40],
        "tenantId": "pilot",
        "workspaceId": "pilot",
        "collectionId": "collection-contract",
        "requestedAt": "2026-09-03T00:00:00.000Z",
        "route": {
            "operationClass": "revision_compile",
            "qualityRequirement": "high_assurance",
            "maxCostCredits": 10,
            "maxLatencyMs": 90000,
            "privacyPolicy": "foundation_synthetic_only",
        },
        "previousWorld": {
            "worldStateId": prior.world_state_id,
            "manifestDigest": prior.manifest_digest,
            "coreOutputSha256": "sha256:" + "b" * 64,
        },
        "documents": {"changed": changed, "unchanged": unchanged},
        "priorArtifactBindings": prior_bindings,
    }


def _post(address, request: dict, *, secret: str = HMAC_SECRET, skew: int = 0):
    """Sign and send exactly as `dispatchProductCoreRevision` does."""
    body = json.dumps(request, separators=(",", ":")).encode("utf-8")
    input_sha256 = "sha256:" + hashlib.sha256(body).hexdigest()
    timestamp = str(int(time.time()) + skew)
    signature = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}\n{request['requestId']}\n{input_sha256}".encode(),
        hashlib.sha256,
    ).hexdigest()
    connection = http.client.HTTPConnection(address[0], address[1], timeout=30)
    try:
        connection.request(
            "POST",
            ROUTE,
            body=body,
            headers={
                "content-type": "application/json",
                "content-length": str(len(body)),
                "x-tavonel-core-timestamp": timestamp,
                "x-tavonel-core-request-id": request["requestId"],
                "x-tavonel-input-sha256": input_sha256,
                "x-tavonel-core-signature": signature,
            },
        )
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode("utf-8")), body, input_sha256
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# the scenario


def test_v1_to_v2_revision_over_http(endpoint):
    address, workspace, prior = endpoint
    request = _build_request(prior)
    status, payload, wire_body, input_sha256 = _post(address, request)

    assert status == 200, payload
    assert payload["schemaVersion"] == "tavonel.product_core.compile_response.v3"
    assert payload["runtime"] == "tavonel-python-core-v2"
    revision = payload["revision"]

    # STEP 5-6 -- the clause is the same clause, and it did change.
    payment = next(
        unit for unit in revision["identity"]["units"] if unit["logicalUnitId"] == "ku_payment"
    )
    assert payment["identityContinuity"] == "continued"
    assert payment["changeState"] == "semantic"
    assert payment["identityFingerprint"] != payment["changeFingerprint"]

    # STEP 7 -- affected is what reads the clause; unaffected is everything else.
    assert set(revision["recompilation"]["rebuiltArtifactIds"]) == {
        "claim:payment",
        "summary:contract",
        "retrieval:payment",
        "graph:relations",
    }
    assert set(revision["recompilation"]["carriedForwardArtifactIds"]) == {
        "claim:law",
        "claim:address",
        "claim:signatories",
    }

    # STEP 9-10 -- against an independently written full rebuild.
    assert revision["equivalence"] == "passed"

    # STEP 11 -- every carried-forward value equals what a full rebuild of the
    # AFTER revision would have produced. That is stale = 0, measured.
    oracle = workspace.oracle(V2_CLAUSES)()
    carried = revision["recompilation"]["carriedForwardDigests"]
    assert carried
    for artifact, value in carried.items():
        assert value == oracle[artifact], artifact
        assert value == prior.artifact_digests[artifact], artifact

    # STEP 12 -- and the saving is real.
    recompilation = revision["recompilation"]
    assert recompilation["totalArtifacts"] == len(ARTIFACTS)
    assert recompilation["workAvoidedArtifacts"] == 3
    assert (
        recompilation["workAvoidedArtifacts"]
        == recompilation["totalArtifacts"] - recompilation["rebuiltArtifacts"]
    )

    # STEP 10 (source facts) -- accounted for, with the one declined loss named.
    assert revision["sourceFacts"]["sourceFaithful"] is True
    assert revision["sourceFacts"]["coveragePermille"] == 1000
    assert revision["sourceFacts"]["failClosed"] == []

    # STEP 13 -- offered to a human, never taken by the compiler.
    assert revision["disposition"] == "promotable"
    assert payload["candidate"]["lifecycle"] == "candidate"
    assert payload["receipt"]["candidatePromotion"] is False
    assert payload["candidate"]["parentWorldStateId"] == "world-v1"

    # STEP 14-16 -- the answer, and the citation.
    answer = workspace.bodies["retrieval:payment"]["reads"][0]
    assert "45 days" in answer["text"]
    assert "30 days" not in answer["text"]
    assert answer["provenance"]["pageNumber1"] == 2
    assert answer["provenance"]["bbox1000"] == [120, 356, 880, 388]
    # The v1 box, specifically, is not what a reader would be sent to.
    assert answer["provenance"]["bbox1000"] != [120, 340, 880, 372]

    _write_fixture(request, wire_body, input_sha256, payload)


def test_the_receipt_seal_is_reproducible_from_the_response(endpoint):
    """The digest the Node client recomputes, recomputed here the other way."""
    address, _workspace, prior = endpoint
    _status, payload, _body, input_sha256 = _post(address, _build_request(prior))
    from akc_core_v3.contract import canonicalize, digest

    assert payload["receipt"]["inputSha256"] == input_sha256
    assert payload["receipt"]["outputSha256"] == digest(canonicalize(payload["revision"]))
    assert payload["receipt"]["coreReleaseDigest"] == CORE_RELEASE


def test_an_unsigned_request_is_refused(endpoint):
    address, _workspace, prior = endpoint
    status, payload, _body, _sha = _post(address, _build_request(prior), secret="x" * 40)
    assert status == 401
    assert payload["code"] == "CORE_V3_SIGNATURE_INVALID"


def test_a_replayed_timestamp_outside_the_window_is_refused(endpoint):
    address, _workspace, prior = endpoint
    status, payload, _body, _sha = _post(address, _build_request(prior), skew=-4000)
    assert status == 401
    assert payload["code"] == "CORE_V3_TIMESTAMP_OUT_OF_WINDOW"


def test_a_body_that_does_not_match_its_digest_is_refused(endpoint):
    address, _workspace, prior = endpoint
    request = _build_request(prior)
    body = json.dumps(request, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    lying_sha = "sha256:" + "0" * 64
    signature = hmac.new(
        HMAC_SECRET.encode("utf-8"),
        f"{timestamp}\n{request['requestId']}\n{lying_sha}".encode(),
        hashlib.sha256,
    ).hexdigest()
    connection = http.client.HTTPConnection(address[0], address[1], timeout=30)
    try:
        connection.request(
            "POST",
            ROUTE,
            body=body,
            headers={
                "content-type": "application/json",
                "content-length": str(len(body)),
                "x-tavonel-core-timestamp": timestamp,
                "x-tavonel-core-request-id": request["requestId"],
                "x-tavonel-input-sha256": lying_sha,
                "x-tavonel-core-signature": signature,
            },
        )
        response = connection.getresponse()
        status = response.status
        payload = json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()
    assert status == 401
    assert payload["code"] == "CORE_V3_INPUT_DIGEST_MISMATCH"


def test_an_initial_compile_operation_class_is_refused_on_this_route(endpoint):
    address, _workspace, prior = endpoint
    request = _build_request(prior)
    request["route"]["operationClass"] = "initial_compile"
    status, payload, _body, _sha = _post(address, request)
    assert status == 400
    assert payload["code"] == "CORE_V3_OPERATION_CLASS_UNSUPPORTED"


def test_a_request_naming_a_world_the_resolver_cannot_produce_is_refused(endpoint):
    address, _workspace, prior = endpoint
    request = _build_request(prior)
    request["previousWorld"]["worldStateId"] = "world-that-was-superseded"
    status, payload, _body, _sha = _post(address, request)
    assert status == 409
    assert payload["code"] == "CORE_V3_PRIOR_WORLD_NOT_RESOLVED"


def test_an_unrepresented_source_fact_stops_the_activation(world_v1):
    """The finding that makes `selective == full` not enough, wired end to end."""
    workspace, prior = world_v1
    facts = [
        *_source_facts(V2_CLAUSES),
        SourceFact(
            fact_id="sf-formula",
            kind="UNSUPPORTED_CONSTRUCT",
            state=SourceFactState.UNRESOLVED,
            reason="no canonical representation for an expression tree",
        ),
    ]
    service = RevisionService(
        hmac_secret=HMAC_SECRET,
        resolve=_resolver(workspace, prior, V2_CLAUSES, facts=facts),
        core_release_digest=CORE_RELEASE,
    )
    httpd, stop = serve(service)
    try:
        status, payload, _body, _sha = _post(httpd.server_address, _build_request(prior))
    finally:
        stop()
    assert status == 200
    revision = payload["revision"]
    # The two builds still agree. That is the whole point: agreement is not
    # source faithfulness, and the compile is stopped by the fact, not by a
    # mismatch.
    assert revision["equivalence"] == "passed"
    assert revision["sourceFacts"]["sourceFaithful"] is False
    assert revision["sourceFacts"]["failClosed"] == ["sf-formula"]
    assert revision["disposition"] == "review_required"
    assert payload["status"] == "review_required"
    assert payload["candidate"]["lifecycle"] == "review_required"


def _write_fixture(request: dict, wire_body: bytes, input_sha256: str, payload: dict) -> None:
    """Emit the cross-language binding.

    `nextjs/lib/core-runtime-revision.crosslang.test.ts` loads this and runs the
    real client validator over it. Regenerated by running this test, never
    hand-edited: a hand-edited fixture proves the editor agreed with the client.
    """
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    # LF explicitly. This artifact is bound by sha256 and a byte-identical copy
    # of it lives in the product repository; letting the platform decide the line
    # ending would make the digest disagree between a Windows working copy and
    # every checkout, which is the one thing an evidence artifact may not do.
    FIXTURE.write_text(
        json.dumps(
            {
                "schema": "tavonel.evidence.revision_compile_e2e.v1",
                "producedBy": "tests/integration/test_revision_compile_e2e.py",
                "coreReleaseDigest": CORE_RELEASE,
                "request": request,
                # The exact bytes that were signed and digested. `request` above
                # is the same object re-serialised with sorted keys by this
                # writer, so its key order is an artifact of the fixture file and
                # not of the wire. The Node client's builder is compared against
                # THIS, which is what actually crossed the socket.
                "requestBody": wire_body.decode("utf-8"),
                "inputSha256": input_sha256,
                "response": payload,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
