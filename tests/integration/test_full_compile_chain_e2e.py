"""The whole chain, from stored OCR to a revised answer, over real sockets.

    real initial_compile
      -> real candidate World v1
      -> activation
      -> real source revision
      -> production SourceResolver
      -> revision_compile
      -> collection projections
      -> promotable World v2
      -> activation
      -> Ask

Every step is performed. Nothing here builds a world by hand: World v1 is what
`InitialCompileService` sealed from the OCR records in the corpus below, and
World v2 is assembled from the bytes `RevisionService` returned. The two services
run behind `http.server` on loopback and are driven with the same signed envelope
the Node client sends.

What made this worth writing rather than extending the existing suite: until now
the first claim of the scenario -- "v1 compile" -- was carried by a test helper.
`Workspace.full_build` produced a deterministic world, so every later assertion
was true, and none of them said anything about compiling a document. The
difference shows up immediately in what the corpus has to contain. A fixture
world can simply declare that clause 4.1 exists on page 2; here the OCR has to
carry a region whose text is "4.1 Payment is due...", the resolver has to decide
that it is a clause rather than a heading, attach it to the section above it, and
give it an anchor that survives the amendment. Those are the steps a real compile
takes, and none of them were previously exercised.

The corpus is two documents so that carry-forward is real: the contract is
amended, the annex is not, and nothing derived from the annex may be rebuilt.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "core-v3" / "src"))

from akc_core_v3.initial import InitialCompileService  # noqa: E402
from akc_core_v3.projections import (  # noqa: E402
    COLLECTION_PROJECTIONS,
    DIRECTORY,
    ONTOLOGY,
    RETRIEVAL_INDEX,
)
from akc_core_v3.resolver import InMemoryWorldArchive, ProductionSourceResolver  # noqa: E402
from akc_core_v3.server import INITIAL_ROUTE, ROUTE, serve  # noqa: E402
from akc_core_v3.service import RevisionService  # noqa: E402
from world_activation import ActivationRefused, WorldStore  # noqa: E402

HMAC_SECRET = "chain-e2e-secret-that-is-long-enough-32+"
CORE_RELEASE = "sha256:" + "c" * 64
TENANT = "pilot"
COLLECTION = "collection-contract"


# ---------------------------------------------------------------------------
# the corpus: OCR as the pipeline actually stores it


def _regions(rows):
    """Build OCR v2 regions, numbering pages and reading order from the rows."""
    return [
        {
            "regionId": region_id,
            "pageIndex0": page - 1,
            "pageNumber1": page,
            "order": order,
            "blockType": "paragraph",
            "text": text,
            "bbox1000": list(bbox),
            "confidence": confidence,
            "authority": "contractual",
        }
        for order, (region_id, page, text, bbox, confidence) in enumerate(rows)
    ]


def _record(rows, *, page_count, immutable_key, version_key):
    regions = _regions(rows)
    text = "\n".join(region["text"] for region in regions).strip()
    return {
        "schemaVersion": "tavonel.ocr_result.v2",
        "versionKey": version_key,
        "pageCount": page_count,
        "text": text,
        "inputSha256": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "sourceImmutableKey": immutable_key,
        "regions": regions,
    }


CONTRACT_V1_ROWS = [
    ("c-r01", 1, "1. Parties", (120, 200, 880, 232), 0.99),
    (
        "c-r02",
        1,
        "1.2 Registered office: 12 Sejong-daero, Jung-gu, Seoul.",
        (120, 560, 880, 592),
        0.98,
    ),
    ("c-r03", 2, "4. Payment", (120, 300, 880, 332), 0.99),
    ("c-r04", 2, "4.1 Payment is due within 30 days of invoice.", (120, 340, 880, 372), 0.98),
    ("c-r05", 3, "Page 3 of 6", (450, 960, 550, 980), 0.95),
    ("c-r06", 4, "9. Governing law", (120, 170, 880, 202), 0.99),
    (
        "c-r07",
        4,
        "9.1 This agreement is governed by the laws of the Republic of Korea.",
        (120, 210, 880, 242),
        0.98,
    ),
    ("c-r08", 5, "10. Signatures", (120, 80, 880, 112), 0.99),
    (
        "c-r09",
        5,
        "10.1 Signed by the authorised representatives of both parties.",
        (120, 120, 880, 152),
        0.97,
    ),
]

# The amendment. The clause changes its words, moves down the page, and is
# recognised as a *different region* -- which is what a re-typeset produces. All
# three at once, because a test where only the words change would not show that
# identity survives the other two.
CONTRACT_V2_ROWS = [
    row
    if row[0] != "c-r04"
    else ("c-r04b", 2, "4.1 Payment is due within 45 days of invoice.", (120, 356, 880, 388), 0.98)
    for row in CONTRACT_V1_ROWS
]

ANNEX_ROWS = [
    ("a-r01", 1, "2. Delivery", (120, 150, 880, 182), 0.99),
    (
        "a-r02",
        1,
        "2.1 Goods are delivered DDP to the buyer's registered office.",
        (120, 190, 880, 222),
        0.98,
    ),
    ("a-r03", 2, "3. Warranty", (120, 150, 880, 182), 0.99),
    (
        "a-r04",
        2,
        "3.1 The seller warrants the goods for twelve months.",
        (120, 190, 880, 222),
        0.97,
    ),
]

CONTRACT_KEY = f"immutable/{TENANT}/doc-contract/source.pdf"
ANNEX_KEY = f"immutable/{TENANT}/doc-annex/source.pdf"

CONTRACT_V1 = _record(CONTRACT_V1_ROWS, page_count=6, immutable_key=CONTRACT_KEY, version_key="v1")
CONTRACT_V2 = _record(CONTRACT_V2_ROWS, page_count=6, immutable_key=CONTRACT_KEY, version_key="v2")
ANNEX_V1 = _record(ANNEX_ROWS, page_count=3, immutable_key=ANNEX_KEY, version_key="v1")

CORPUS = {
    f"immutable/{TENANT}/doc-contract/v1/ocr.json": CONTRACT_V1,
    f"immutable/{TENANT}/doc-contract/v2/ocr.json": CONTRACT_V2,
    f"immutable/{TENANT}/doc-annex/v1/ocr.json": ANNEX_V1,
}

PAYMENT = "ku_doc-contract_4_1"
ANNEX_WARRANTY = "ku_doc-annex_3_1"


class Corpus:
    """Immutable storage, read-only, recording what was asked for.

    The reads are recorded so a test can assert that the revision resolved the
    *whole* collection rather than only the document that changed -- a
    resolution that skipped the annex would compile a world in which the annex
    had been deleted, and every digest in it would still be internally
    consistent.
    """

    def __init__(self) -> None:
        self.reads: list[str] = []

    def get_json(self, key: str):
        self.reads.append(key)
        if key not in CORPUS:
            raise KeyError(key)
        return CORPUS[key]


def _document(document_id: str, version: str, record, *, title: str, previous=None):
    entry = {
        "nativeId": document_id,
        "connectorType": "foundation-r2",
        "immutableObjectKey": record["sourceImmutableKey"],
        "ocrObjectKey": f"immutable/{TENANT}/{document_id}/{version}/ocr.json",
        "contentSha256": record["inputSha256"],
        "title": title,
        "sourceFilename": f"{document_id}.pdf",
        "pageCount": record["pageCount"],
    }
    if previous is not None:
        entry["previousContentSha256"] = previous["inputSha256"]
    return entry


# ---------------------------------------------------------------------------
# the wire, signed as the Node client signs it


def _post(address, path: str, request: dict, *, secret: str = HMAC_SECRET):
    body = json.dumps(request, separators=(",", ":")).encode("utf-8")
    input_sha = "sha256:" + hashlib.sha256(body).hexdigest()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}\n{request['requestId']}\n{input_sha}".encode(),
        hashlib.sha256,
    ).hexdigest()
    connection = http.client.HTTPConnection(*address, timeout=30)
    try:
        connection.request(
            "POST",
            path,
            body=body,
            headers={
                "content-type": "application/json",
                "content-length": str(len(body)),
                "x-tavonel-core-timestamp": timestamp,
                "x-tavonel-core-request-id": request["requestId"],
                "x-tavonel-input-sha256": input_sha,
                "x-tavonel-core-signature": signature,
            },
        )
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()


def _initial_request(documents: list[dict]) -> dict:
    return {
        "schemaVersion": "tavonel.product_core.compile_request.v3",
        "requestId": "core-initial-chain",
        "idempotencyKey": "initial-" + hashlib.sha256(
            "\n".join(sorted(d["contentSha256"] for d in documents)).encode("utf-8")
        ).hexdigest()[:40],
        "tenantId": TENANT,
        "workspaceId": TENANT,
        "collectionId": COLLECTION,
        "requestedAt": "2026-09-03T00:00:00.000Z",
        "route": {
            "operationClass": "initial_compile",
            "qualityRequirement": "high_assurance",
            "maxCostCredits": 10,
            "maxLatencyMs": 90000,
            "privacyPolicy": "foundation_synthetic_only",
        },
        "documents": {"initial": documents},
    }


def _revision_request(world: dict, changed: list[dict], unchanged: list[dict]) -> dict:
    """The request the Node client builds, field for field.

    Mirrored rather than imported, because the client is TypeScript. The
    orderings below are by code point for the same reason the client's are: an
    ICU-locale-dependent sort would make the signed bytes and the idempotency key
    differ between two workers compiling the same revision.
    """
    prior_bindings = [
        {"artifactId": artifact, "contentSha256": world["digests"][artifact]}
        for artifact in sorted(world["digests"])
    ]
    binding = "\n".join(
        [
            world["worldStateId"],
            world["manifestDigest"],
            world["coreOutputSha256"],
            *[
                f"{item['nativeId']}:{item['previousContentSha256']}->{item['contentSha256']}"
                for item in sorted(changed, key=lambda x: x["nativeId"])
            ],
            *[
                f"{item['nativeId']}={item['contentSha256']}"
                for item in sorted(unchanged, key=lambda x: x["nativeId"])
            ],
        ]
    )
    return {
        "schemaVersion": "tavonel.product_core.compile_request.v3",
        "requestId": "core-rev-chain",
        "idempotencyKey": "revision-" + hashlib.sha256(binding.encode("utf-8")).hexdigest()[:40],
        "tenantId": TENANT,
        "workspaceId": TENANT,
        "collectionId": COLLECTION,
        "requestedAt": "2026-09-03T00:05:00.000Z",
        "route": {
            "operationClass": "revision_compile",
            "qualityRequirement": "high_assurance",
            "maxCostCredits": 10,
            "maxLatencyMs": 90000,
            "privacyPolicy": "foundation_synthetic_only",
        },
        "previousWorld": {
            "worldStateId": world["worldStateId"],
            "manifestDigest": world["manifestDigest"],
            "coreOutputSha256": world["coreOutputSha256"],
        },
        "documents": {
            "changed": sorted(changed, key=lambda x: x["nativeId"]),
            "unchanged": sorted(unchanged, key=lambda x: x["nativeId"]),
        },
        "priorArtifactBindings": prior_bindings,
    }


# ---------------------------------------------------------------------------
# the chain


class Chain:
    """Both services, the archive they share, and the store that reads them."""

    def __init__(self) -> None:
        self.corpus = Corpus()
        self.archive = InMemoryWorldArchive()
        self.initial = InitialCompileService(
            hmac_secret=HMAC_SECRET,
            store=self.corpus,
            core_release_digest=CORE_RELEASE,
            archive=self.archive,
        )
        self.revision = RevisionService(
            hmac_secret=HMAC_SECRET,
            resolve=ProductionSourceResolver(store=self.corpus, archive=self.archive),
            core_release_digest=CORE_RELEASE,
        )
        self.store = WorldStore()
        self._httpd, self._stop = serve(self.revision, initial=self.initial)

    @property
    def address(self):
        return self._httpd.server_address

    def close(self) -> None:
        self._stop()

    # -- step 1: compile World v1 from the sources ---------------------------

    def compile_v1(self) -> dict:
        status, payload = _post(
            self.address,
            INITIAL_ROUTE,
            _initial_request(
                [
                    _document("doc-contract", "v1", CONTRACT_V1, title="Supply agreement"),
                    _document("doc-annex", "v1", ANNEX_V1, title="Annex"),
                ]
            ),
        )
        assert status == 200, payload
        return payload

    def register_v1(self, payload: dict) -> dict:
        artifacts = payload["initial"]["artifacts"]
        # Every body the compile returned must hash to the digest it sealed
        # beside it. Registering without this check would let the store hold
        # bytes the receipt does not describe.
        for artifact_id, body in artifacts["bodies"].items():
            assert _digest_of(body) == artifacts["digests"][artifact_id], artifact_id
        self.store.register(
            world_state_id=payload["candidate"]["worldStateId"],
            manifest_digest=payload["candidate"]["manifestDigest"],
            artifacts=dict(artifacts["bodies"]),
            lifecycle=payload["candidate"]["lifecycle"],
            candidate_promotion=payload["receipt"]["candidatePromotion"],
        )
        return {
            "worldStateId": payload["candidate"]["worldStateId"],
            "manifestDigest": payload["candidate"]["manifestDigest"],
            "coreOutputSha256": payload["receipt"]["outputSha256"],
            "digests": dict(artifacts["digests"]),
        }

    # -- step 2: compile the revision against the active world ---------------

    def compile_v2(self, world: dict):
        return _post(
            self.address,
            ROUTE,
            _revision_request(
                world,
                changed=[
                    _document(
                        "doc-contract",
                        "v2",
                        CONTRACT_V2,
                        title="Supply agreement",
                        previous=CONTRACT_V1,
                    )
                ],
                unchanged=[_document("doc-annex", "v1", ANNEX_V1, title="Annex")],
            ),
        )

    def assemble_v2(self, world: dict, payload: dict) -> str:
        """Build World v2 the way a caller must: carry forward, take the rebuilt."""
        recompiled = payload["revision"]["recompilation"]
        artifacts: dict[str, object] = {}
        for artifact_id in recompiled["carriedForwardArtifactIds"]:
            assert recompiled["carriedForwardDigests"][artifact_id] == world["digests"][artifact_id]
            artifacts[artifact_id] = self.store.read(artifact_id)
        for artifact_id, body in recompiled["rebuiltArtifactBodies"].items():
            assert _digest_of(body) == recompiled["rebuiltDigests"][artifact_id]
            artifacts[artifact_id] = body
        manifest = payload["candidate"]["manifestDigest"]
        self.store.register(
            world_state_id=payload["candidate"]["worldStateId"],
            manifest_digest=manifest,
            artifacts=artifacts,
            lifecycle=payload["candidate"]["lifecycle"],
            candidate_promotion=payload["receipt"]["candidatePromotion"],
        )
        return manifest


def _digest_of(body) -> str:
    content = (
        body
        if isinstance(body, str)
        else json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


@pytest.fixture
def chain():
    running = Chain()
    try:
        yield running
    finally:
        running.close()


# ---------------------------------------------------------------------------
# claims 1-2: a compile, and the world it produced


def test_world_v1_is_compiled_from_stored_ocr(chain):
    """Claim 1 and 2. The world is what the service built, not what a test declared.

    The assertions are about things the fixture never had to get right: which
    regions became units, which section each one landed under, what anchor it
    took, and that the page furniture was declined under a policy rather than
    dropped.
    """
    payload = chain.compile_v1()
    initial = payload["initial"]

    assert payload["status"] == "completed"
    assert payload["candidate"]["lifecycle"] == "candidate"
    assert payload["candidate"]["parentWorldStateId"] is None
    assert payload["receipt"]["candidatePromotion"] is False

    # It read both documents out of storage, by the version-scoped key.
    assert sorted(chain.corpus.reads) == [
        f"immutable/{TENANT}/doc-annex/v1/ocr.json",
        f"immutable/{TENANT}/doc-contract/v1/ocr.json",
    ]

    units = {unit["logicalUnitId"]: unit for unit in initial["units"]}
    assert set(units) == {
        "ku_doc-contract_1_2",
        PAYMENT,
        "ku_doc-contract_9_1",
        "ku_doc-contract_10_1",
        "ku_doc-annex_2_1",
        ANNEX_WARRANTY,
    }
    # The anchor is the printed clause number, and the section is the heading
    # above it -- both derived by walking the regions, neither declared.
    assert units[PAYMENT]["explicitIdentifier"] == "4.1"
    assert units[PAYMENT]["section"] == "4. Payment"
    assert units[PAYMENT]["provenance"]["pageNumber1"] == 2
    assert units[PAYMENT]["provenance"]["bbox1000"] == [120, 340, 880, 372]
    assert units[PAYMENT]["provenance"]["regionId"] == "c-r04"

    # Every region is accounted for: four headings and eight clause facts from
    # the contract, two headings and four from the annex, and the folio declined
    # under a policy that existed before the run.
    facts = initial["sourceFacts"]
    assert facts["coveragePermille"] == 1000
    assert facts["sourceFaithful"] is True
    assert facts["failClosed"] == []
    assert facts["tally"]["IGNORED_BY_PREDECLARED_POLICY"] == 1
    assert facts["tally"]["RECOGNIZED_BUT_UNREPRESENTED"] == 0
    assert facts["tally"]["UNRESOLVED_SOURCE_FACT"] == 0


def test_the_collection_projections_are_artifacts_of_the_world(chain):
    """Claim 2, the half that was blocking the Product.

    They are in the same digest map as every other artifact, under reserved ids,
    each with its own dependency sensitivity. Being listed separately is a
    convenience for the caller; being *in* the map is the contract.
    """
    initial = chain.compile_v1()["initial"]
    artifacts = initial["artifacts"]

    assert initial["collectionProjections"] == list(COLLECTION_PROJECTIONS)
    for projection in COLLECTION_PROJECTIONS:
        assert projection in artifacts["digests"], projection
        assert projection in artifacts["bodies"], projection
        assert artifacts["digests"][projection].startswith("sha256:")

    # Sensitivity is declared, not inferred. The directory is structural only,
    # which is what lets it survive an amendment two tests below.
    assert artifacts["sensitivity"][DIRECTORY] == ["structural"]
    assert artifacts["sensitivity"][ONTOLOGY] == ["semantic", "structural"]
    assert artifacts["sensitivity"][RETRIEVAL_INDEX] == ["locator", "semantic", "visual"]

    # The directory carries structure and no clause text. If it carried a
    # snippet "for readability" every wording change would rebuild it.
    directory = json.dumps(artifacts["bodies"][DIRECTORY])
    assert "4. Payment" in directory
    assert "30 days" not in directory


def test_an_initial_compile_will_not_promote_itself(chain):
    payload = chain.compile_v1()
    assert payload["receipt"]["candidatePromotion"] is False
    with pytest.raises(ActivationRefused, match="a compile may not promote itself"):
        chain.store.register(
            world_state_id="w",
            manifest_digest="sha256:" + "0" * 64,
            artifacts={},
            lifecycle="candidate",
            candidate_promotion=True,
        )
        chain.store.activate(
            manifest_digest="sha256:" + "0" * 64,
            expected_current_manifest=None,
            actor="nobody",
            reason="trying",
        )


# ---------------------------------------------------------------------------
# claims 3-17: the scenario


def test_the_whole_chain(chain):
    """Claims 3 through 17, in order, through both services.

    This is the scenario the product claim rests on, run rather than described.
    """
    # -- claims 1-3: compile v1, then a person activates it -----------------
    v1_payload = chain.compile_v1()
    world_v1 = chain.register_v1(v1_payload)
    chain.store.activate(
        manifest_digest=world_v1["manifestDigest"],
        expected_current_manifest=None,
        actor="reviewer@tavonel",
        reason="initial review of the supply agreement and its annex",
    )

    before = chain.store.read(f"retrieval:{PAYMENT}")["reads"][0]
    assert "30 days" in before["text"]

    # -- claim 4: the source is revised; the resolver reads it --------------
    chain.corpus.reads.clear()
    status, payload = chain.compile_v2(world_v1)
    assert status == 200, payload
    assert payload["revision"]["disposition"] == "promotable"

    # The revision resolved the whole collection, not only what changed.
    assert sorted(set(chain.corpus.reads)) == [
        f"immutable/{TENANT}/doc-annex/v1/ocr.json",
        f"immutable/{TENANT}/doc-contract/v2/ocr.json",
    ]

    revision = payload["revision"]
    units = {unit["logicalUnitId"]: unit for unit in revision["identity"]["units"]}

    # -- claim 5: identity continued across the amendment -------------------
    assert units[PAYMENT]["identityContinuity"] == "continued"

    # -- claim 6: and the change was still detected -------------------------
    assert units[PAYMENT]["changeState"] == "semantic"
    assert units[PAYMENT]["identityFingerprint"] != units[PAYMENT]["changeFingerprint"]
    # The re-typeset travelled on its own channels rather than being folded into
    # the semantic one: the evidence occurrence moved, and so did the box.
    assert "locator" in units[PAYMENT]["changeStates"]
    # Nothing in the annex changed at all.
    assert units[ANNEX_WARRANTY]["changeState"] == "unchanged"

    # -- claims 7-9: impact, carry-forward, selective rebuild ---------------
    recompiled = revision["recompilation"]
    rebuilt = set(recompiled["rebuiltArtifactIds"])
    carried = set(recompiled["carriedForwardArtifactIds"])

    assert f"claim:{PAYMENT}" in rebuilt
    assert f"retrieval:{PAYMENT}" in rebuilt
    assert "summary:doc-contract" in rebuilt
    assert ONTOLOGY in rebuilt
    assert RETRIEVAL_INDEX in rebuilt

    # Nothing derived from the annex is rebuilt, and neither is the structural
    # projection: the amendment changed words, not the shape of the collection.
    assert f"claim:{ANNEX_WARRANTY}" in carried
    assert "summary:doc-annex" in carried
    assert DIRECTORY in carried
    assert rebuilt.isdisjoint(carried)
    assert rebuilt | carried == set(world_v1["digests"])

    # -- claim 12: nothing stale was carried ---------------------------------
    for artifact_id in carried:
        assert recompiled["carriedForwardDigests"][artifact_id] == world_v1["digests"][artifact_id]

    # -- claim 13: and work was actually avoided -----------------------------
    total = recompiled["totalArtifacts"]
    assert recompiled["workAvoidedArtifacts"] == total - len(rebuilt)
    assert recompiled["workAvoidedArtifacts"] > 0

    # -- claim 10: against an independent full rebuild -----------------------
    assert revision["equivalence"] == "passed"

    # -- claim 11: every source fact still accounted for ---------------------
    assert revision["sourceFacts"]["sourceFaithful"] is True
    assert revision["sourceFacts"]["failClosed"] == []
    assert revision["sourceFacts"]["coveragePermille"] == 1000

    # -- claim 14: a candidate, and only a candidate -------------------------
    assert payload["candidate"]["lifecycle"] == "candidate"
    assert payload["receipt"]["candidatePromotion"] is False

    manifest_v2 = chain.assemble_v2(world_v1, payload)
    assert chain.store.active_manifest == world_v1["manifestDigest"]
    assert "30 days" in chain.store.read(f"retrieval:{PAYMENT}")["reads"][0]["text"]

    # -- claim 15: a person activates World v2 -------------------------------
    chain.store.activate(
        manifest_digest=manifest_v2,
        expected_current_manifest=world_v1["manifestDigest"],
        actor="reviewer@tavonel",
        reason="payment term amended from 30 to 45 days",
    )

    # -- claim 16: Ask, read through the active pointer ----------------------
    answer = chain.store.read(f"retrieval:{PAYMENT}")["reads"][0]
    assert "45 days" in answer["text"]
    assert "30 days" not in answer["text"]

    # -- claim 17: and the citation opens the amended clause -----------------
    assert answer["provenance"]["pageNumber1"] == 2
    assert answer["provenance"]["bbox1000"] == [120, 356, 880, 388]
    assert answer["provenance"]["bbox1000"] != [120, 340, 880, 372]
    assert answer["provenance"]["regionId"] == "c-r04b"

    # The collection-level answer moved with it, and the annex did not.
    chunks = {c["chunkId"]: c for c in chain.store.read(RETRIEVAL_INDEX)["chunks"]}
    assert "45 days" in chunks[f"chunk:{PAYMENT}"]["text"]
    assert chunks[f"chunk:{PAYMENT}"]["provenance"]["bbox1000"] == [120, 356, 880, 388]
    assert "twelve months" in chunks[f"chunk:{ANNEX_WARRANTY}"]["text"]

    # v1 is retained, not overwritten, and both activations are recorded.
    assert chain.store.versions[world_v1["manifestDigest"]]["status"] == "superseded"
    assert chain.store.versions[manifest_v2]["status"] == "active"
    assert len(chain.store.events) == 2


def test_the_witness_chain_survives_the_revision(chain):
    """Claim 11's other half: provenance continuity, artifact by artifact.

    An unrelated artifact must carry not only the same digest but the same
    witness. A carried-forward file whose evidence pointer had silently moved
    would still match its digest -- the digest is over the file, and the file is
    the one that did not change -- so the witness is checked separately.
    """
    v1_payload = chain.compile_v1()
    world_v1 = chain.register_v1(v1_payload)
    chain.store.activate(
        manifest_digest=world_v1["manifestDigest"],
        expected_current_manifest=None,
        actor="reviewer@tavonel",
        reason="initial review",
    )
    v1_witnesses = v1_payload["initial"]["witnesses"]

    status, payload = chain.compile_v2(world_v1)
    assert status == 200
    manifest_v2 = chain.assemble_v2(world_v1, payload)
    chain.store.activate(
        manifest_digest=manifest_v2,
        expected_current_manifest=world_v1["manifestDigest"],
        actor="reviewer@tavonel",
        reason="amendment",
    )

    # Untouched units keep the exact witness v1 recorded.
    for logical_id in ("ku_doc-contract_9_1", ANNEX_WARRANTY, "ku_doc-annex_2_1"):
        read = chain.store.read(f"claim:{logical_id}")["reads"][0]
        assert read["provenance"] == v1_witnesses[logical_id], logical_id

    # The amended one does not, and every field of the difference is real.
    amended = chain.store.read(f"claim:{PAYMENT}")["reads"][0]["provenance"]
    assert amended != v1_witnesses[PAYMENT]
    assert amended["documentId"] == v1_witnesses[PAYMENT]["documentId"]
    assert amended["pageNumber1"] == v1_witnesses[PAYMENT]["pageNumber1"] == 2
    assert amended["bbox1000"] != v1_witnesses[PAYMENT]["bbox1000"]
    assert amended["evidenceId"] != v1_witnesses[PAYMENT]["evidenceId"]


def test_a_revision_against_an_unknown_world_is_refused(chain):
    """The archive lookup is a check, not a formality."""
    v1_payload = chain.compile_v1()
    world_v1 = chain.register_v1(v1_payload)
    moved = dict(world_v1, manifestDigest="sha256:" + "f" * 64)
    status, payload = chain.compile_v2(moved)
    assert status == 409
    assert payload["code"] == "CORE_V3_PRIOR_WORLD_NOT_RESOLVED"


def test_the_initial_route_refuses_a_revision_and_the_revision_route_refuses_a_compile(chain):
    """Each route answers for one operation class and says so.

    An operation class that either endpoint would satisfy carries no
    information, and the failure it hides -- a revision compiled as a first
    world -- produces a candidate with no predecessor and a plausible receipt.
    """
    world = {
        "worldStateId": "world-x",
        "manifestDigest": "sha256:" + "a" * 64,
        "coreOutputSha256": "sha256:" + "b" * 64,
        "digests": {},
    }
    revision_request = _revision_request(world, changed=[], unchanged=[])
    revision_request["documents"]["changed"] = [
        _document("doc-contract", "v2", CONTRACT_V2, title="c", previous=CONTRACT_V1)
    ]
    status, payload = _post(chain.address, INITIAL_ROUTE, revision_request)
    assert status == 400
    assert payload["code"] == "CORE_V3_OPERATION_CLASS_UNSUPPORTED"

    status, payload = _post(
        chain.address,
        ROUTE,
        _initial_request([_document("doc-contract", "v1", CONTRACT_V1, title="c")]),
    )
    assert status == 400
    assert payload["code"] == "CORE_V3_OPERATION_CLASS_UNSUPPORTED"


def test_an_initial_request_that_names_a_predecessor_is_refused(chain):
    request = _initial_request([_document("doc-contract", "v1", CONTRACT_V1, title="c")])
    request["previousWorld"] = {
        "worldStateId": "world-x",
        "manifestDigest": "sha256:" + "a" * 64,
        "coreOutputSha256": "sha256:" + "b" * 64,
    }
    status, payload = _post(chain.address, INITIAL_ROUTE, request)
    assert status == 400
    assert payload["code"] == "CORE_V3_INITIAL_HAS_NO_PREDECESSOR"


def test_a_document_whose_stored_bytes_are_not_the_ones_named_is_refused(chain):
    """The digest binding between request and storage, checked.

    Without this the compile would be of a different document than the one whose
    lineage the receipt claims -- and every digest in the result would still be
    internally consistent, which is what makes it worth checking here rather
    than leaving for whoever later tries to reconcile a world against its
    sources.
    """
    document = _document("doc-contract", "v1", CONTRACT_V1, title="c")
    document["contentSha256"] = "sha256:" + "9" * 64
    status, payload = _post(chain.address, INITIAL_ROUTE, _initial_request([document]))
    assert status == 422
    assert payload["code"] == "CORE_V3_SOURCE_DIGEST_MISMATCH"


def test_a_document_with_no_regions_fails_closed(chain):
    """OCR without page or box cannot ground an answer, so it is not summarised."""
    key = f"immutable/{TENANT}/doc-flat/v1/ocr.json"
    flat = {
        "schemaVersion": "tavonel.ocr_result.v1",
        "versionKey": "v1",
        "pageCount": 2,
        "text": "4.1 Payment is due within 30 days of invoice.",
        "inputSha256": "sha256:"
        + hashlib.sha256(b"4.1 Payment is due within 30 days of invoice.").hexdigest(),
        "sourceImmutableKey": f"immutable/{TENANT}/doc-flat/source.pdf",
    }
    CORPUS[key] = flat
    try:
        document = {
            "nativeId": "doc-flat",
            "connectorType": "foundation-r2",
            "immutableObjectKey": flat["sourceImmutableKey"],
            "ocrObjectKey": key,
            "contentSha256": flat["inputSha256"],
            "title": "Flat",
            "sourceFilename": "flat.pdf",
            "pageCount": 2,
        }
        status, payload = _post(chain.address, INITIAL_ROUTE, _initial_request([document]))
        # No unit survives, so there is nothing to compile a world from.
        assert status == 422
        assert payload["code"] == "CORE_V3_NO_RESOLVABLE_UNIT"
    finally:
        del CORPUS[key]


def test_low_confidence_text_is_unresolved_and_forces_review(chain):
    """A recogniser that does not stand behind its output does not make a claim.

    The compile still happens and the world is still built -- the point is that
    it arrives as `review_required` with the fact named, rather than as a
    candidate whose coverage silently dropped.
    """
    key = f"immutable/{TENANT}/doc-blur/v1/ocr.json"
    rows = [
        ("b-r01", 1, "5. Term", (120, 100, 880, 132), 0.99),
        ("b-r02", 1, "5.1 This agreement runs for three years.", (120, 140, 880, 172), 0.99),
        (
            "b-r03",
            1,
            "5.2 Renewal is automatic unless notice is given.",
            (120, 180, 880, 212),
            0.20,
        ),
    ]
    record = _record(
        rows,
        page_count=1,
        immutable_key=f"immutable/{TENANT}/doc-blur/source.pdf",
        version_key="v1",
    )
    CORPUS[key] = record
    try:
        document = {
            "nativeId": "doc-blur",
            "connectorType": "foundation-r2",
            "immutableObjectKey": record["sourceImmutableKey"],
            "ocrObjectKey": key,
            "contentSha256": record["inputSha256"],
            "title": "Blurred",
            "sourceFilename": "blur.pdf",
            "pageCount": 1,
        }
        status, payload = _post(chain.address, INITIAL_ROUTE, _initial_request([document]))
        assert status == 200
        assert payload["status"] == "review_required"
        assert payload["candidate"]["lifecycle"] == "review_required"
        facts = payload["initial"]["sourceFacts"]
        assert facts["sourceFaithful"] is False
        assert facts["failClosed"] == ["sf-doc-blur-b-r03"]
        assert facts["coveragePermille"] < 1000

        # And it cannot be activated, even though every digest is consistent.
        chain.store.register(
            world_state_id=payload["candidate"]["worldStateId"],
            manifest_digest=payload["candidate"]["manifestDigest"],
            artifacts=dict(payload["initial"]["artifacts"]["bodies"]),
            lifecycle=payload["candidate"]["lifecycle"],
            candidate_promotion=payload["receipt"]["candidatePromotion"],
        )
        with pytest.raises(ActivationRefused, match="not activatable"):
            chain.store.activate(
                manifest_digest=payload["candidate"]["manifestDigest"],
                expected_current_manifest=None,
                actor="reviewer@tavonel",
                reason="activating over an unresolved source fact",
            )
    finally:
        del CORPUS[key]


def test_the_same_sources_compile_to_the_same_world(chain):
    """Determinism, and independence from the order the documents arrive in.

    A manifest that depended on request order would make every re-compile look
    like a change, and the revision path would then rebuild a world that nothing
    had actually revised.
    """
    first = chain.compile_v1()
    reversed_request = _initial_request(
        [
            _document("doc-annex", "v1", ANNEX_V1, title="Annex"),
            _document("doc-contract", "v1", CONTRACT_V1, title="Supply agreement"),
        ]
    )
    reversed_request["requestId"] = "core-initial-chain-2"
    status, second = _post(chain.address, INITIAL_ROUTE, reversed_request)
    assert status == 200
    assert second["candidate"]["manifestDigest"] == first["candidate"]["manifestDigest"]
    assert second["initial"]["artifacts"]["digests"] == first["initial"]["artifacts"]["digests"]
    assert second["receipt"]["outputSha256"] == first["receipt"]["outputSha256"]
