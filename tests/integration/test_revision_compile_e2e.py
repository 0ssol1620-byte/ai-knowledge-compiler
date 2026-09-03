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


def digest_of_text(content: str) -> str:
    """The digest of raw content, which is what `artifact_content` produces."""
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


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


def _resolver(
    workspace: Workspace,
    prior: PriorWorld,
    after: tuple[Clause, ...],
    *,
    facts=None,
    materialise=None,
):
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
            materialise=materialise or (lambda artifact: workspace.bodies[artifact]),
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

    # The rebuilt bodies travel with the receipt that seals their digests, so a
    # caller holding World v1 can assemble World v2 without trusting a second
    # channel: carry forward the bytes it already has, take these for the rest.
    recompiled = payload["revision"]["recompilation"]
    assert set(recompiled["rebuiltArtifactBodies"]) == set(recompiled["rebuiltArtifactIds"])
    for artifact_id, artifact_body in recompiled["rebuiltArtifactBodies"].items():
        assert _digest_of(artifact_body) == recompiled["rebuiltDigests"][artifact_id]
    assert not set(recompiled["rebuiltDigests"]) & set(recompiled["carriedForwardDigests"])
    amended = recompiled["rebuiltArtifactBodies"]["claim:payment"]["reads"][0]
    assert "45 days" in amended["text"]
    assert amended["provenance"]["bbox1000"] == [120, 356, 880, 388]

    # STEP 14-16 -- the answer, and the citation.
    answer = workspace.bodies["retrieval:payment"]["reads"][0]
    assert "45 days" in answer["text"]
    assert "30 days" not in answer["text"]
    assert answer["provenance"]["pageNumber1"] == 2
    assert answer["provenance"]["bbox1000"] == [120, 356, 880, 388]
    # The v1 box, specifically, is not what a reader would be sent to.
    assert answer["provenance"]["bbox1000"] != [120, 340, 880, 372]

    _write_fixture(request, wire_body, input_sha256, payload)


def test_the_witness_chain_survives_the_revision(endpoint):
    """Provenance is carried, not re-derived, and it is carried per artifact.

    The chain the product rests on is raw source -> page and box -> canonical
    unit -> source fact -> claim -> derived artifact. A revision is where that
    chain is easiest to lose: the tempting implementation re-derives provenance
    for everything it touches, and then an artifact nobody rebuilt quietly
    acquires coordinates that were computed rather than observed.

    So this asks both halves. What was carried forward must still point at the
    page and box v1 recorded, byte for byte. What was rebuilt must point at v2's,
    and specifically not at v1's.
    """
    address, workspace, prior = endpoint
    v1_provenance = {artifact: _artifact_body(artifact, V1_CLAUSES) for artifact in ARTIFACTS}

    status, payload, _body, _sha = _post(address, _build_request(prior))
    assert status == 200, payload
    recompiled = payload["revision"]["recompilation"]

    # Carried forward: identical to v1, including every evidence id, page and box.
    for artifact_id in recompiled["carriedForwardArtifactIds"]:
        assert workspace.bodies[artifact_id] == v1_provenance[artifact_id]
        for read in workspace.bodies[artifact_id]["reads"]:
            before = next(
                item
                for item in v1_provenance[artifact_id]["reads"]
                if item["logicalId"] == read["logicalId"]
            )
            assert read["provenance"] == before["provenance"]

    # Rebuilt: the amended clause moved, so its witness moved with it. Every
    # other unit inside a rebuilt artifact keeps the coordinates it always had --
    # rebuilding an artifact must not re-derive provenance for the units in it
    # that did not change.
    for artifact_id in recompiled["rebuiltArtifactIds"]:
        for read in recompiled["rebuiltArtifactBodies"][artifact_id]["reads"]:
            before = next(
                item
                for item in v1_provenance[artifact_id]["reads"]
                if item["logicalId"] == read["logicalId"]
            )
            if read["logicalId"] == "ku_payment":
                assert read["provenance"]["bbox1000"] == [120, 356, 880, 388]
                assert read["provenance"] != before["provenance"]
            else:
                assert read["provenance"] == before["provenance"]

    # And the evidence id is bound to the page the clause is actually on, not to
    # the unit alone -- a revision that moved a clause between pages and kept the
    # old evidence id would still pass every digest check above.
    payment = recompiled["rebuiltArtifactBodies"]["claim:payment"]["reads"][0]
    assert payment["provenance"]["evidenceId"] == "ev_ku_payment_p2"
    assert payment["provenance"]["pageNumber1"] == 2


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


def test_a_rebuilt_body_that_does_not_match_its_sealed_digest_is_refused(world_v1):
    """The bodies are only worth carrying if they cannot disagree with the seal.

    A materialiser that returns something other than what the builder hashed is
    the realistic version of this failure: a cache serving a previous revision's
    bytes, or a read from the wrong key. The receipt would still be internally
    consistent -- its digests describe the compile that happened -- while the
    bodies beside it describe a different one, and the caller assembling the
    next world from those bodies has no way to notice.
    """
    workspace, prior = world_v1

    def stale(artifact: str) -> dict[str, object]:
        # v1's bytes for the clause that changed: the exact thing a stale read
        # would hand back, and the exact thing the digest check has to catch.
        return _artifact_body(artifact, V1_CLAUSES)

    service = RevisionService(
        hmac_secret=HMAC_SECRET,
        resolve=_resolver(workspace, prior, V2_CLAUSES, materialise=stale),
        core_release_digest=CORE_RELEASE,
    )
    httpd, stop = serve(service)
    try:
        status, payload, _body, _sha = _post(httpd.server_address, _build_request(prior))
    finally:
        stop()
    assert status == 500
    assert payload == {"code": "CORE_V3_REBUILT_BODY_DIGEST_MISMATCH"}


def test_a_rebuilt_artifact_may_be_raw_content_rather_than_a_document(world_v1):
    """CSV, JSON Lines and Turtle are half of what a caller has to assemble.

    Forcing them through JSON quoting so one convention could cover everything
    would make a rebuilt file's digest differ from the digest of the file it
    replaces, and the package it was rebuilt into would fail its own integrity
    check for a reason that has nothing to do with the compile.
    """
    workspace, prior = world_v1
    rows = {
        artifact: "artifact,logical_id\n"
        + "".join(f"{artifact},{unit}\n" for unit in READS[artifact])
        for artifact in ARTIFACTS
    }

    def build(artifact: str) -> str:
        return digest_of_text(rows[artifact])

    resolve = _resolver(workspace, prior, V2_CLAUSES, materialise=lambda a: rows[a])
    base = resolve(None)
    service = RevisionService(
        hmac_secret=HMAC_SECRET,
        resolve=lambda request: replace(base, build=build, full_rebuild=None),
        core_release_digest=CORE_RELEASE,
    )
    httpd, stop = serve(service)
    try:
        status, payload, _body, _sha = _post(httpd.server_address, _build_request(prior))
    finally:
        stop()
    assert status == 200, payload
    recompiled = payload["revision"]["recompilation"]
    for artifact_id, artifact_body in recompiled["rebuiltArtifactBodies"].items():
        assert isinstance(artifact_body, str)
        assert artifact_body == rows[artifact_id]
        assert digest_of_text(artifact_body) == recompiled["rebuiltDigests"][artifact_id]


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


# ---------------------------------------------------------------------------
# activation -- the step the scenario claimed and no test performed


class ActivationRefused(RuntimeError):
    """A world was offered for activation and the store declined."""


class WorldStore:
    """The activation contract, modelled.

    This is not PostgreSQL. Production activation is `promote_foundation_candidate`
    with an advisory transaction lock and `FOR UPDATE`, and it has its own tests in
    `supabase/tests/foundation_world_lifecycle.sql`.

    What is modelled here is the part the *compile* path has to satisfy, because
    until now the end-to-end scenario asserted only that activation was withheld
    and never that it could be performed: activation is explicit rather than a
    consequence of compiling, it is bound to the manifest the actor believed was
    current, a candidate carrying open findings cannot be activated at all, and
    the world being replaced is retained rather than overwritten.
    """

    def __init__(self) -> None:
        self.versions: dict[str, dict[str, object]] = {}
        self.active_manifest: str | None = None
        self.events: list[tuple[str, str]] = []

    def register(
        self,
        *,
        world_state_id: str,
        manifest_digest: str,
        artifacts: dict[str, dict[str, object]],
        lifecycle: str,
        candidate_promotion: bool,
    ) -> None:
        if manifest_digest in self.versions:
            raise ActivationRefused("a candidate is immutable once registered")
        self.versions[manifest_digest] = {
            "world_state_id": world_state_id,
            "artifacts": artifacts,
            "lifecycle": lifecycle,
            "candidate_promotion": candidate_promotion,
            "status": "candidate",
        }

    def activate(
        self,
        *,
        manifest_digest: str,
        expected_current_manifest: str | None,
        actor: str,
        reason: str,
    ) -> None:
        if manifest_digest not in self.versions:
            raise ActivationRefused("no such candidate")
        version = self.versions[manifest_digest]
        if version["lifecycle"] != "candidate":
            # review_required and rejected are not activatable. The Core said as
            # much in the response; the store refuses independently rather than
            # trusting the caller to have read it.
            raise ActivationRefused(f"lifecycle {version['lifecycle']} is not activatable")
        if version["candidate_promotion"] is not False:
            raise ActivationRefused("a compile may not promote itself")
        if expected_current_manifest != self.active_manifest:
            # Optimistic concurrency. Somebody else activated between this actor
            # reading the world and deciding to replace it, and that change would
            # be silently lost.
            raise ActivationRefused("active world moved since it was read")
        if not reason.strip():
            raise ActivationRefused("activation requires a stated reason")
        if self.active_manifest is not None:
            self.versions[self.active_manifest]["status"] = "superseded"
        version["status"] = "active"
        self.active_manifest = manifest_digest
        self.events.append((actor, manifest_digest))

    def read(self, artifact_id: str) -> dict[str, object]:
        """Read through the active pointer, the only way a reader sees a world."""
        if self.active_manifest is None:
            raise ActivationRefused("no active world")
        artifacts = self.versions[self.active_manifest]["artifacts"]
        return artifacts[artifact_id]  # type: ignore[index]


def _activated_world_v1() -> tuple[Workspace, PriorWorld, WorldStore]:
    workspace = Workspace()
    digests = workspace.full_build(V1_CLAUSES)
    manifest = _digest_of({"world": "v1", "artifacts": digests})
    prior = PriorWorld(
        world_state_id="world-v1",
        manifest_digest=manifest,
        artifact_digests=digests,
        source_sha256="sha256:" + "1" * 64,
        units=[clause.snapshot() for clause in V1_CLAUSES],
        shape=_shape(V1_CLAUSES),
    )
    store = WorldStore()
    store.register(
        world_state_id="world-v1",
        manifest_digest=manifest,
        artifacts={a: _artifact_body(a, V1_CLAUSES) for a in ARTIFACTS},
        lifecycle="candidate",
        candidate_promotion=False,
    )
    store.activate(
        manifest_digest=manifest,
        expected_current_manifest=None,
        actor="reviewer@tavonel",
        reason="initial review of the supply agreement",
    )
    return workspace, prior, store


def _assemble_v2(store: WorldStore, prior: PriorWorld, payload: dict) -> str:
    """Build World v2 the way a caller must: carry forward, take the rebuilt bytes."""
    recompiled = payload["revision"]["recompilation"]
    artifacts: dict[str, dict[str, object]] = {}
    for artifact_id in recompiled["carriedForwardArtifactIds"]:
        # Carried forward means the bytes already held, not a re-derivation, and
        # the digest the Core returned must equal the one this side sent.
        assert (
            recompiled["carriedForwardDigests"][artifact_id] == prior.artifact_digests[artifact_id]
        )
        artifacts[artifact_id] = store.read(artifact_id)
    for artifact_id, body in recompiled["rebuiltArtifactBodies"].items():
        assert _digest_of(body) == recompiled["rebuiltDigests"][artifact_id]
        artifacts[artifact_id] = body
    assert set(artifacts) == set(ARTIFACTS), "the next world must cover every artifact"
    manifest = payload["candidate"]["manifestDigest"]
    store.register(
        world_state_id=payload["candidate"]["worldStateId"],
        manifest_digest=manifest,
        artifacts=artifacts,
        lifecycle=payload["candidate"]["lifecycle"],
        candidate_promotion=payload["receipt"]["candidatePromotion"],
    )
    return manifest


def test_the_scenario_end_to_end_including_both_activations():
    """The whole claim, with the two activations actually performed.

    Every other test here stops at the candidate and asserts that activation was
    withheld. That is the fail-closed half, and it was the only half being tested:
    the scenario said "compiled, reviewed and activated as World v1" and "a human
    activates World v2", and nothing performed either step.

    So this runs it. World v1 is activated by a named reviewer, the revision is
    compiled against the world that is actually active, World v2 is assembled from
    carried bytes plus rebuilt bytes, a human activates it against the manifest
    they read, and the question is answered by reading through the active pointer
    rather than out of the compiler workspace.
    """
    workspace, prior, store = _activated_world_v1()
    v1_manifest = prior.manifest_digest

    # Before the revision, the active world answers with the original term.
    before = store.read("retrieval:payment")["reads"][0]
    assert "30 days" in before["text"]

    service = RevisionService(
        hmac_secret=HMAC_SECRET,
        resolve=_resolver(workspace, prior, V2_CLAUSES),
        core_release_digest=CORE_RELEASE,
    )
    httpd, stop = serve(service)
    try:
        status, payload, _body, _sha = _post(httpd.server_address, _build_request(prior))
    finally:
        stop()
    assert status == 200, payload
    assert payload["revision"]["disposition"] == "promotable"
    assert payload["receipt"]["candidatePromotion"] is False

    v2_manifest = _assemble_v2(store, prior, payload)

    # Still v1 until a person says otherwise. Compiling is not activating.
    assert store.active_manifest == v1_manifest
    assert "30 days" in store.read("retrieval:payment")["reads"][0]["text"]

    store.activate(
        manifest_digest=v2_manifest,
        expected_current_manifest=v1_manifest,
        actor="reviewer@tavonel",
        reason="payment term amended from 30 to 45 days",
    )

    # The answer, read through the active pointer.
    answer = store.read("retrieval:payment")["reads"][0]
    assert "45 days" in answer["text"]
    assert "30 days" not in answer["text"]
    assert answer["provenance"]["pageNumber1"] == 2
    assert answer["provenance"]["bbox1000"] == [120, 356, 880, 388]
    assert answer["provenance"]["bbox1000"] != [120, 340, 880, 372]
    assert answer["provenance"]["evidenceId"] == "ev_ku_payment_p2"

    # Unrelated facts are unchanged and still carry the witness v1 recorded.
    law = store.read("claim:law")["reads"][0]
    assert law["provenance"] == _artifact_body("claim:law", V1_CLAUSES)["reads"][0]["provenance"]

    # v1 is retained, not overwritten.
    assert store.versions[v1_manifest]["status"] == "superseded"
    assert store.versions[v2_manifest]["status"] == "active"
    assert len(store.events) == 2


def test_activation_is_refused_when_the_active_world_moved():
    """Optimistic concurrency, at the activation boundary.

    Two reviewers read World v1 and both decide to replace it. The second must
    not silently discard the first, and the store refuses rather than resolving
    it -- which of the two worlds should survive is not a question code can answer.
    """
    workspace, prior, store = _activated_world_v1()
    service = RevisionService(
        hmac_secret=HMAC_SECRET,
        resolve=_resolver(workspace, prior, V2_CLAUSES),
        core_release_digest=CORE_RELEASE,
    )
    httpd, stop = serve(service)
    try:
        _status, payload, _body, _sha = _post(httpd.server_address, _build_request(prior))
    finally:
        stop()
    v2_manifest = _assemble_v2(store, prior, payload)

    with pytest.raises(ActivationRefused, match="active world moved"):
        store.activate(
            manifest_digest=v2_manifest,
            expected_current_manifest=_digest_of({"world": "a different one"}),
            actor="second-reviewer@tavonel",
            reason="racing the first reviewer",
        )
    assert store.active_manifest == prior.manifest_digest


def test_a_candidate_with_an_open_finding_cannot_be_activated():
    """The fail-closed half, now checked against a store that can say yes.

    An assertion that activation was withheld means little from a store that has
    never activated anything. This one has: it activated World v1 a few lines
    earlier, and it still refuses this candidate.
    """
    workspace, prior, store = _activated_world_v1()
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
        _status, payload, _body, _sha = _post(httpd.server_address, _build_request(prior))
    finally:
        stop()
    assert payload["candidate"]["lifecycle"] == "review_required"
    v2_manifest = _assemble_v2(store, prior, payload)

    with pytest.raises(ActivationRefused, match="not activatable"):
        store.activate(
            manifest_digest=v2_manifest,
            expected_current_manifest=prior.manifest_digest,
            actor="reviewer@tavonel",
            reason="trying to activate over an unresolved source fact",
        )
    assert store.active_manifest == prior.manifest_digest
    assert "30 days" in store.read("retrieval:payment")["reads"][0]["text"]
