"""Drive the real core chain over the FP-200 fixture and write down what it did.

    initial compile (revision B world)
      -> revision compile (revision C)
      -> plan_recompilation
      -> selective rebuild
      -> full rebuild
      -> verify_equivalence

Nothing in this file compiles anything itself. It builds the signed request the
Node client builds, hands it to `InitialCompileService` and `RevisionService`,
and records what came back. Where the sealed response carries a count but not
the object behind it -- `RecompilationPlan`, `EquivalenceReport` -- the same
request is resolved a second time through `ProductionSourceResolver` and passed
to `compile_revision` directly, and the two results are cross-checked. A receipt
whose plan came from one run and whose manifest came from another would be a
receipt about nothing.

**The headline result is a refusal.** The FP-200 corpus the site publishes is
unnumbered prose, and `akc_core_v3.sources.canonicalise_document` builds units
only from printed clause numbers under printed numbered headings. Every region
of all four documents resolves to `UNNUMBERED_PARAGRAPH` /
`UNRESOLVED_SOURCE_FACT`, no unit survives, and `resolve_sources` refuses with
`CORE_V3_NO_RESOLVABLE_UNIT`. That is run 1, and it is the deliverable: a named
gap with the run behind it rather than an assertion.

Runs 2 and 3 exist to say *where* the boundary is, because "blocked" on its own
does not distinguish a resolver that cannot read the shape from a chain that
cannot do the job. They compile a clause-form restatement -- the same sentences
under printed clause numbers -- through the same unmodified services. Run 2
gives the manual one document id across both revisions, which is what identity
continuity requires; run 3 gives it the two ids the site's filenames imply, and
measures what that costs. Neither is the fixture the site serves, both say so in
their own record, and neither may be wired into `/explore` as an equivalence
result.

No core module is modified by this file or by anything it imports. Determinism:
every request id, idempotency key and `requestedAt` is fixed, and the envelope
clock is pinned, so the deterministic half of the receipt is byte-stable.

    python research/explore_change_receipt_20260905/build_receipt.py
"""

from __future__ import annotations

import hashlib
import hmac
import json
import platform
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
INPUTS = HERE / "inputs"
RECEIPT = HERE / "receipt.json"

# The interpreter that runs this may not have the workspace packages installed;
# pytest supplies them through `pythonpath` in pyproject.toml, a bare `python`
# does not. Added ahead of site-packages so a stale installed copy cannot answer
# for the checkout being measured.
for _package in ("services/core-v3/src", "packages/cir-python/src"):
    _path = str(REPO / _package)
    if _path not in sys.path:
        sys.path.insert(0, _path)

from akc_cir.recompilation import (  # noqa: E402
    EquivalenceReport,
    RecompilationPlan,
    verify_equivalence,
)
from akc_cir.revision_compile import RevisionCompileResult, compile_revision  # noqa: E402
from akc_core_v3.initial import InitialCompileService  # noqa: E402
from akc_core_v3.resolver import InMemoryWorldArchive, ProductionSourceResolver  # noqa: E402
from akc_core_v3.service import RevisionService  # noqa: E402
from akc_core_v3.sources import canonicalise_document, load_document  # noqa: E402

__all__ = ["build", "document_reference", "input_manifest", "main", "ocr_record"]

#: The core commit this receipt describes. Section 0 of the lane contract.
AKC_COMMIT = "26bb8926334246bbc666d6cc5abbb7291dac53f1"

#: Not a credential. The envelope is HMAC-signed and both ends of the signature
#: are in this file, so the value is a fixture constant with no authority
#: anywhere: it authenticates a request this process makes to a service this
#: process constructed. It is long enough only because the service refuses a
#: shorter one.
ENVELOPE_KEY = "explore-change-receipt-20260905-fixture-envelope"

#: Neither is this. `check_release_digest` requires the shape, and no deployed
#: release is being named.
CORE_RELEASE_DIGEST = "sha256:" + "0" * 64

TENANT = "research"
COLLECTION = "fp200-maintenance"

#: A pinned clock, so the signed bytes and the receipt are the same on every run.
FIXED_EPOCH = 1_772_668_800  # 2026-03-05T00:00:00Z
REQUESTED_AT = "2026-03-05T00:00:00.000Z"

#: One document id for the manual across both revisions. `logical_id` is
#: `ku_{document_id}_{clause}`, so this is what makes clause 2.1 of revision C
#: the same unit as clause 2.1 of revision B rather than a new one.
MANUAL = "fp200-maintenance-manual"

MANUAL_REV_B = "fp200-maintenance-manual-rev-b"
MANUAL_REV_C = "fp200-maintenance-manual-rev-c"
CLAUSE_MANUAL_REV_B = "fp200-maintenance-manual-clause-rev-b"
CLAUSE_MANUAL_REV_C = "fp200-maintenance-manual-clause-rev-c"


# ---------------------------------------------------------------------------
# inputs


def _load(name: str) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = json.loads((INPUTS / name).read_text(encoding="utf-8"))
    return parsed


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def input_manifest() -> list[dict[str, str]]:
    """Every file under `inputs/`, with its digest. Sorted, so it is stable."""
    return [
        {
            "path": path.relative_to(HERE).as_posix(),
            "bytes": str(path.stat().st_size),
            "sha256": _sha256_file(path),
        }
        for path in sorted(INPUTS.rglob("*"))
        if path.is_file()
    ]


class Corpus:
    """Read-only immutable storage over the records this receipt was built from.

    Records what was asked for, so the receipt can say whether a revision
    resolved the whole collection or only the document that changed.
    """

    def __init__(self, records: Mapping[str, Mapping[str, Any]]) -> None:
        self._records = dict(records)
        self.reads: list[str] = []

    def get_json(self, key: str) -> Any:
        self.reads.append(key)
        return self._records[key]


def ocr_record(entry: Mapping[str, Any]) -> dict[str, Any]:
    """The stored OCR object, in the shape `load_document` validates."""
    return {
        "schemaVersion": "tavonel.ocr_result.v2",
        "versionKey": entry["versionKey"],
        "pageCount": entry["pageCount"],
        "text": entry["text"],
        "inputSha256": entry["inputSha256"],
        "sourceImmutableKey": entry["sourceImmutableKey"],
        "regions": entry["regions"],
    }


def document_reference(
    entry: Mapping[str, Any],
    *,
    native_id: str,
    title: str,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The document reference a compile request carries."""
    reference = {
        "nativeId": native_id,
        "connectorType": "research-fixture",
        "immutableObjectKey": entry["sourceImmutableKey"],
        "ocrObjectKey": entry["ocrJsonKey"],
        "contentSha256": entry["inputSha256"],
        "title": title,
        "sourceFilename": entry["sanitizedKey"].split("/")[-1],
        "pageCount": entry["pageCount"],
    }
    if previous is not None:
        reference["previousContentSha256"] = previous["inputSha256"]
    return reference


# ---------------------------------------------------------------------------
# the wire


def _headers(body: bytes, request_id: str) -> dict[str, str]:
    input_sha = "sha256:" + hashlib.sha256(body).hexdigest()
    timestamp = str(FIXED_EPOCH)
    signature = hmac.new(
        ENVELOPE_KEY.encode("utf-8"),
        f"{timestamp}\n{request_id}\n{input_sha}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return {
        "content-type": "application/json",
        "x-tavonel-core-timestamp": timestamp,
        "x-tavonel-core-request-id": request_id,
        "x-tavonel-input-sha256": input_sha,
        "x-tavonel-core-signature": signature,
    }


def _encode(request: Mapping[str, Any]) -> bytes:
    return json.dumps(request, separators=(",", ":"), sort_keys=False).encode("utf-8")


def _route(operation_class: str) -> dict[str, Any]:
    return {
        "operationClass": operation_class,
        "qualityRequirement": "high_assurance",
        "maxCostCredits": 10,
        "maxLatencyMs": 90000,
        "privacyPolicy": "foundation_synthetic_only",
    }


def _initial_request(documents: Sequence[Mapping[str, Any]], *, request_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": "tavonel.product_core.compile_request.v3",
        "requestId": request_id,
        "idempotencyKey": "initial-"
        + hashlib.sha256(
            "\n".join(sorted(str(d["contentSha256"]) for d in documents)).encode("utf-8")
        ).hexdigest()[:40],
        "tenantId": TENANT,
        "workspaceId": TENANT,
        "collectionId": COLLECTION,
        "requestedAt": REQUESTED_AT,
        "route": _route("initial_compile"),
        "documents": {"initial": list(documents)},
    }


def _revision_request(
    world: Mapping[str, Any],
    changed: Sequence[Mapping[str, Any]],
    unchanged: Sequence[Mapping[str, Any]],
    *,
    request_id: str,
) -> dict[str, Any]:
    """The request the Node client builds, ordered by code point as it orders."""
    binding = "\n".join(
        [
            str(world["worldStateId"]),
            str(world["manifestDigest"]),
            str(world["coreOutputSha256"]),
            *[
                f"{item['nativeId']}:{item['previousContentSha256']}->{item['contentSha256']}"
                for item in sorted(changed, key=lambda entry: str(entry["nativeId"]))
            ],
            *[
                f"{item['nativeId']}={item['contentSha256']}"
                for item in sorted(unchanged, key=lambda entry: str(entry["nativeId"]))
            ],
        ]
    )
    return {
        "schemaVersion": "tavonel.product_core.compile_request.v3",
        "requestId": request_id,
        "idempotencyKey": "revision-"
        + hashlib.sha256(binding.encode("utf-8")).hexdigest()[:40],
        "tenantId": TENANT,
        "workspaceId": TENANT,
        "collectionId": COLLECTION,
        "requestedAt": REQUESTED_AT,
        "route": _route("revision_compile"),
        "previousWorld": {
            "worldStateId": world["worldStateId"],
            "manifestDigest": world["manifestDigest"],
            "coreOutputSha256": world["coreOutputSha256"],
        },
        "documents": {
            "changed": sorted(changed, key=lambda item: str(item["nativeId"])),
            "unchanged": sorted(unchanged, key=lambda item: str(item["nativeId"])),
        },
        "priorArtifactBindings": [
            {"artifactId": artifact, "contentSha256": world["digests"][artifact]}
            for artifact in sorted(world["digests"])
        ],
    }


class Chain:
    """Both services and the archive they share, over one corpus."""

    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus
        self.archive = InMemoryWorldArchive()
        self.resolver = ProductionSourceResolver(store=corpus, archive=self.archive)
        self.initial = InitialCompileService(
            hmac_secret=ENVELOPE_KEY,
            store=corpus,
            core_release_digest=CORE_RELEASE_DIGEST,
            archive=self.archive,
            now=lambda: float(FIXED_EPOCH),
        )
        self.revision = RevisionService(
            hmac_secret=ENVELOPE_KEY,
            resolve=self.resolver,
            core_release_digest=CORE_RELEASE_DIGEST,
            now=lambda: float(FIXED_EPOCH),
        )

    def compile_initial(
        self, documents: Sequence[Mapping[str, Any]], *, request_id: str
    ) -> tuple[int, dict[str, Any]]:
        body = _encode(_initial_request(documents, request_id=request_id))
        return self.initial.handle(_headers(body, request_id), body)

    def compile_revision(
        self, request: Mapping[str, Any], *, request_id: str
    ) -> tuple[int, dict[str, Any]]:
        body = _encode(request)
        return self.revision.handle(_headers(body, request_id), body)


# ---------------------------------------------------------------------------
# run 1 -- the site fixture, verbatim


def _fact_ledger(corpus: Corpus, documents: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Why each region did or did not become a unit, document by document.

    `resolve_sources` reports only that nothing survived. This walks the same
    canonicaliser over the same documents so the refusal names the regions
    behind it rather than a count.
    """
    ledger: list[dict[str, Any]] = []
    for document_ref in documents:
        document = load_document(
            corpus,
            document_id=str(document_ref["nativeId"]),
            title=str(document_ref["title"]),
            ocr_object_key=str(document_ref["ocrObjectKey"]),
            immutable_object_key=str(document_ref["immutableObjectKey"]),
            content_sha256=str(document_ref["contentSha256"]),
            page_count=int(document_ref["pageCount"]),
        )
        units, facts = canonicalise_document(document)
        ledger.append(
            {
                "documentId": document.document_id,
                "sourceSha256": document.input_sha256,
                "regions": len(document.regions),
                "units": len(units),
                "facts": [
                    {
                        "factId": fact.fact_id,
                        "kind": fact.kind,
                        "state": fact.state.value,
                        "reason": fact.reason,
                    }
                    for fact in facts
                ],
            }
        )
    return ledger


def run_site_fixture_verbatim() -> dict[str, Any]:
    """Compile the revision-B world from the documents the site publishes."""
    entries = {entry["documentId"]: entry for entry in _load("site-fixture.inputs.json")}
    corpus = Corpus({entry["ocrJsonKey"]: ocr_record(entry) for entry in entries.values()})
    chain = Chain(corpus)

    documents = [
        document_reference(
            entries[MANUAL_REV_B], native_id=MANUAL, title="FP-200 maintenance manual"
        ),
        document_reference(
            entries["fp200-change-notice-cn-2026-03"],
            native_id="fp200-change-notice-cn-2026-03",
            title="FP-200 change notice CN-2026-03",
        ),
        document_reference(
            entries["fp200-service-log-2026"],
            native_id="fp200-service-log-2026",
            title="FP-200 service log 2026",
        ),
    ]

    status, payload = chain.compile_initial(documents, request_id="site-fixture-initial")
    ledger = _fact_ledger(corpus, documents)
    return {
        "run": "site_fixture_verbatim",
        "question": (
            "does the core chain compile the FP-200 documents the site publishes, "
            "as they are written"
        ),
        "corpusIsSiteFixture": True,
        "wireableIntoExplore": False,
        "outcome": "refused" if status != 200 else "compiled",
        "httpStatus": status,
        "refusalCode": payload.get("code"),
        "documents": [
            {
                "nativeId": document["nativeId"],
                "sourceFilename": document["sourceFilename"],
                "contentSha256": document["contentSha256"],
            }
            for document in documents
        ],
        "unitsResolved": sum(int(item["units"]) for item in ledger),
        "regionsSeen": sum(int(item["regions"]) for item in ledger),
        "sourceFactLedger": ledger,
    }


# ---------------------------------------------------------------------------
# runs 2 and 3 -- the clause-form restatement


def _selective_sets(
    result: RevisionCompileResult,
) -> tuple[dict[str, str], dict[str, str]]:
    selective = {
        artifact: result.state[artifact] for artifact in result.rebuilt_artifact_ids
    }
    carried = {
        artifact: result.state[artifact] for artifact in result.carried_forward_artifact_ids
    }
    return selective, carried


def _plan_record(plan: RecompilationPlan) -> dict[str, Any]:
    return {
        "changeId": plan.change_id,
        "totalArtifacts": plan.total_artifacts,
        "toRebuild": list(plan.to_rebuild),
        "stale": list(plan.stale),
        "unresolved": list(plan.unresolved),
        "workAvoided": plan.work_avoided,
        "cyclesDetected": [list(cycle) for cycle in plan.cycles_detected],
        "truncatedAtDepth": plan.truncated_at_depth,
        "facetResolutions": [item.as_record() for item in plan.facet_resolutions],
    }


def run_clause_form(*, shared_document_id: bool) -> dict[str, Any]:
    """Compile revision B, then revise it to revision C, over the restatement.

    `shared_document_id` is the whole difference between run 2 and run 3. With
    it, the manual keeps one id across both revisions and clause 2.1 continues;
    without it, revision C is a different document and every unit of the manual
    is new. Both are run rather than argued.
    """
    entries = {entry["documentId"]: entry for entry in _load("clause-form.inputs.json")}
    corpus = Corpus({entry["ocrJsonKey"]: ocr_record(entry) for entry in entries.values()})
    chain = Chain(corpus)

    manual_b_id = MANUAL if shared_document_id else CLAUSE_MANUAL_REV_B
    manual_c_id = MANUAL if shared_document_id else CLAUSE_MANUAL_REV_C
    notice = document_reference(
        entries["fp200-change-notice-clause-cn-2026-03"],
        native_id="fp200-change-notice-cn-2026-03",
        title="FP-200 change notice CN-2026-03",
    )
    log = document_reference(
        entries["fp200-service-log-clause-2026"],
        native_id="fp200-service-log-2026",
        title="FP-200 service log 2026",
    )
    manual_b = document_reference(
        entries[CLAUSE_MANUAL_REV_B], native_id=manual_b_id, title="FP-200 maintenance manual"
    )
    manual_c = document_reference(
        entries[CLAUSE_MANUAL_REV_C],
        native_id=manual_c_id,
        title="FP-200 maintenance manual",
        previous=entries[CLAUSE_MANUAL_REV_B],
    )

    suffix = "shared" if shared_document_id else "split"

    # -- the revision-B world -------------------------------------------------
    status_b, world_b = chain.compile_initial(
        [manual_b, notice, log], request_id=f"clause-{suffix}-initial"
    )
    if status_b != 200:
        return {
            "run": f"clause_form_{suffix}_document_id",
            "outcome": "refused",
            "httpStatus": status_b,
            "refusalCode": world_b.get("code"),
        }

    initial_artifacts = world_b["initial"]["artifacts"]
    previous = {
        "worldStateId": world_b["candidate"]["worldStateId"],
        "manifestDigest": world_b["candidate"]["manifestDigest"],
        "coreOutputSha256": world_b["receipt"]["outputSha256"],
        "digests": dict(initial_artifacts["digests"]),
    }

    # -- the revision-C compile, through the signed service -------------------
    corpus.reads.clear()
    request = _revision_request(
        previous, [manual_c], [notice, log], request_id=f"clause-{suffix}-revision"
    )
    status_c, world_c = chain.compile_revision(request, request_id=f"clause-{suffix}-revision")
    sealed_reads = sorted(set(corpus.reads))

    if status_c not in (200, 422) or "revision" not in world_c:
        return {
            "run": f"clause_form_{suffix}_document_id",
            "outcome": "refused",
            "httpStatus": status_c,
            "refusalCode": world_c.get("code"),
        }

    # -- the same request again, for the objects the seal does not carry ------
    #
    # `RevisionService` returns counts; `RecompilationPlan` and
    # `EquivalenceReport` are objects. Resolving the identical request a second
    # time through the same production resolver is what makes them the plan and
    # the report *of this compile* -- checked below against the sealed digest.
    resolution = chain.resolver(request)
    result = compile_revision(
        source_id=resolution.source_id,
        previous=resolution.previous,
        after_units=resolution.after_units,
        after_shape=resolution.after_shape,
        after_sha256=resolution.after_sha256,
        graph=resolution.graph,
        artifacts=resolution.artifacts,
        build=resolution.build,
        source_facts=resolution.source_facts,
        full_rebuild=resolution.full_rebuild,
    )
    selective, carried = _selective_sets(result)
    assert resolution.full_rebuild is not None
    oracle = dict(resolution.full_rebuild())
    report: EquivalenceReport = verify_equivalence(
        full_rebuild=oracle,
        selective_rebuild=selective,
        carried_over=carried,
        plan=result.plan,
    )

    revision = world_c["revision"]
    agrees = (
        result.change_id == revision["changeId"]
        and sorted(result.rebuilt_artifact_ids)
        == sorted(revision["recompilation"]["rebuiltArtifactIds"])
        and result.equivalence == revision["equivalence"]
    )

    # Where an artifact was reused and a full rebuild disagrees, both bodies are
    # recorded. `stale_left_behind` is the failure mode the whole module exists
    # to catch, and a list of artifact ids does not say what went stale -- the
    # two bodies side by side do.
    carried_bodies: Mapping[str, Any] = initial_artifacts["bodies"]
    # `materialise` is the plan's own body function, evaluated over the AFTER
    # units -- the same one the full rebuild digests, so this is the body the
    # oracle hashed rather than a second rendering of it.
    assert resolution.materialise is not None
    materialise = resolution.materialise
    divergence = [
        {
            "artifactId": artifact,
            "carriedForwardDigest": carried.get(artifact),
            "fullRebuildDigest": oracle.get(artifact),
            "carriedForwardBody": carried_bodies.get(artifact),
            "fullRebuildBody": materialise(artifact),
        }
        for artifact in report.stale_left_behind
    ]

    units = {unit["logicalUnitId"]: unit for unit in revision["identity"]["units"]}
    return {
        "run": f"clause_form_{suffix}_document_id",
        "question": (
            "does the unmodified core chain carry one clause amendment through "
            "identity, impact, selective rebuild and equivalence"
            if shared_document_id
            else "what does giving each revision its own document id cost"
        ),
        "corpusIsSiteFixture": False,
        "wireableIntoExplore": False,
        "caveat": (
            "The corpus is a clause-form restatement written for this receipt. It is "
            "not the FP-200 documents the site serves, no PDF of it is published, and "
            "this result is not an equivalence claim about /explore."
        ),
        "documentIdPolicy": (
            "one id across both revisions" if shared_document_id else "one id per revision"
        ),
        "outcome": "compiled",
        "httpStatus": status_c,
        "initial": {
            "worldStateId": world_b["candidate"]["worldStateId"],
            "manifestDigest": world_b["candidate"]["manifestDigest"],
            "lifecycle": world_b["candidate"]["lifecycle"],
            "status": world_b["status"],
            "sourceSha256": world_b["initial"]["sourceSha256"],
            "artifactCount": initial_artifacts["totalArtifacts"],
            "artifactDigests": dict(initial_artifacts["digests"]),
            "sourceFacts": world_b["initial"]["sourceFacts"],
        },
        "revisionResolvedKeys": sealed_reads,
        "revision": {
            "changeId": revision["changeId"],
            "worldStateId": world_c["candidate"]["worldStateId"],
            "parentWorldStateId": world_c["candidate"]["parentWorldStateId"],
            "manifestDigest": world_c["candidate"]["manifestDigest"],
            "lifecycle": world_c["candidate"]["lifecycle"],
            "status": world_c["status"],
            "disposition": revision["disposition"],
            "reviewReasons": world_c["candidate"]["reviewReasons"],
            "candidatePromotion": world_c["receipt"]["candidatePromotion"],
            "identityCounts": {
                key: revision["identity"][key]
                for key in ("continued", "new", "ambiguous", "unresolved")
            },
            "typedChanges": revision["typedChanges"],
            "unresolvedChannels": revision["unresolvedChannels"],
            "changedUnits": sorted(
                logical
                for logical, unit in units.items()
                if unit["changeState"] != "unchanged"
            ),
            # From the direct compile rather than the sealed response: the seal
            # drops `identityReason`, which is the only place the resolver says
            # why it declined to settle an identity.
            "units": [record.as_record() for record in result.units],
            "impact": revision["impact"],
            "sourceFacts": revision["sourceFacts"],
            "artifactDigests": dict(result.state),
        },
        "plan": _plan_record(result.plan),
        "selectiveRebuild": {
            "rebuilt": sorted(selective),
            "carriedOver": sorted(carried),
            "quarantined": list(result.quarantined_artifact_ids),
            "unnecessaryRebuild": list(result.unnecessary_rebuild_artifact_ids),
            "counts": {
                "totalArtifacts": result.total_artifacts,
                "rebuilt": len(result.rebuilt_artifact_ids),
                "carriedOver": len(result.carried_forward_artifact_ids),
                "quarantined": len(result.quarantined_artifact_ids),
                "workAvoided": result.work_avoided_artifacts,
            },
        },
        "fullRebuild": {"artifactDigests": oracle},
        "equivalence": report.as_record(),
        "staleLeftBehindWitness": divergence,
        "sealedResponseAgreesWithDirectCompile": agrees,
    }


# ---------------------------------------------------------------------------
# the receipt


def canonical(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def deterministic() -> dict[str, Any]:
    """Everything the chain produced. Byte-stable across runs and machines."""
    runs = [
        run_site_fixture_verbatim(),
        run_clause_form(shared_document_id=True),
        run_clause_form(shared_document_id=False),
    ]
    site = runs[0]
    return {
        "schema": "tavonel.research.explore_change_receipt.v1",
        "campaign": "TAVONEL-CATEGORY-LEADERSHIP-20260905-V1",
        "lane": "change-receipt",
        "akcCommit": AKC_COMMIT,
        "status": "blocked",
        "summary": (
            "The core chain cannot compile the FP-200 fixture the site publishes: its "
            "source resolver builds units only from printed clause numbers, the fixture "
            "is unnumbered prose, every region fails closed and the compile is refused "
            "before a world exists. Compiling a clause-form restatement through the same "
            "unmodified services reaches the end of the chain and does not pass it -- the "
            "amended clause's identity is unsettled, two artifacts are quarantined, the "
            "revision is review_required rather than promotable, and full-rebuild "
            "equivalence fails on two claims that were carried forward with a stale "
            "bounding box. No full-rebuild equivalence PASS exists on this fixture from "
            "either run, so nothing here may be wired into /explore as an equivalence "
            "result."
        ),
        "equivalencePassAvailable": False,
        "blockedBy": [
            {
                "id": "F1",
                "gap": "unit-extraction",
                "function": "akc_core_v3.sources.canonicalise_document",
                "file": "services/core-v3/src/akc_core_v3/sources.py:457-495 "
                "(the _CLAUSE / _HEADING branches), refusing at :576",
                "requiredInputShape": (
                    "a region matching _CLAUSE (a number containing at least one dot, "
                    "then the clause body) beneath a region matching _HEADING (a number, "
                    "then a heading of at most 60 characters containing no full stop)"
                ),
                "actualInputShape": (
                    "unnumbered prose paragraphs; no region of any of the four FP-200 "
                    "documents carries a printed clause number"
                ),
                "observedState": "UNRESOLVED_SOURCE_FACT / UNNUMBERED_PARAGRAPH on every region",
                "refusal": "CORE_V3_NO_RESOLVABLE_UNIT raised by resolve_sources",
                "evidence": "runs[0]",
            },
            {
                "id": "F2",
                "gap": "document-identity-across-revisions",
                "function": "akc_core_v3.sources.canonicalise_document",
                "file": "services/core-v3/src/akc_core_v3/sources.py:498 "
                "-- logical_id = ku_{document_id}_{clause}",
                "requiredInputShape": (
                    "one nativeId for the manual with two contentSha256 versions; "
                    "logical_id is ku_{document_id}_{clause}, so the document id is what "
                    "carries identity across a revision"
                ),
                "actualInputShape": (
                    "the site publishes revision B and revision C as two files whose "
                    "documentIds differ (fp200-maintenance-manual-rev-b / -rev-c)"
                ),
                "observedState": (
                    "measured in runs[2]: with one id per revision no unit continues "
                    "and the manual is reported replaced rather than amended"
                ),
                "refusal": None,
                "evidence": "runs[1] versus runs[2]",
            },
        ],
        "findings": [
            {
                "id": "F3",
                "kind": "correctness",
                "severity": "high",
                "title": (
                    "a claim artifact declares semantic sensitivity and carries locator "
                    "fields in its body, so a clause that keeps its words and moves on "
                    "the page is carried forward with a stale bounding box"
                ),
                "where": [
                    "services/core-v3/src/akc_core_v3/projections.py:230 "
                    "-- channels[claim_id(unit)] = _SEMANTIC",
                    "services/core-v3/src/akc_core_v3/projections.py:208-218 "
                    "-- the claim body embeds unit.provenance(), which is page, bbox, "
                    "evidenceId and regionId",
                    "services/core-v3/src/akc_core_v3/projections.py:66-71 "
                    "-- the comment states the intent: a claim does not go stale when "
                    "the evidence moves",
                ],
                "measured": (
                    "runs[1].equivalence.stale_left_behind names two claims; "
                    "runs[1].staleLeftBehindWitness holds both bodies, whose text is "
                    "byte-identical and whose bbox1000 differs"
                ),
                "notFixedHere": (
                    "projections.py belongs to no lane in this campaign and changing "
                    "artifact sensitivity is an architecture decision; reported, not "
                    "touched"
                ),
            },
            {
                "id": "F4",
                "kind": "expected-behaviour",
                "severity": "informational",
                "title": (
                    "the amended clause's identity is AMBIGUOUS with a single candidate: "
                    "the uncalibrated review band abstaining as designed, not a defect"
                ),
                "where": [
                    "packages/cir-python/src/akc_cir/identity.py:252-256 "
                    "-- MERGE_THRESHOLD 0.92, NEW_IDENTITY_THRESHOLD 0.75, declared a "
                    "bootstrap band and not a calibrated operating point",
                ],
                "measured": (
                    "runs[1].revision.units, the record whose identityContinuity is "
                    "'ambiguous', carries its own identityReason; the consequence is two "
                    "quarantined artifacts and a review_required disposition"
                ),
                "notFixedHere": (
                    "CLAUDE.md: no threshold in this repository is calibrated and none "
                    "may be moved to make a run pass"
                ),
            },
        ],
        "protectedCoreModified": False,
        "coreFilesModified": [],
        "inputs": input_manifest(),
        "runs": runs,
        "siteFixtureUnitsResolved": site["unitsResolved"],
    }


def build() -> dict[str, Any]:
    core = deterministic()
    return {
        "deterministic": core,
        "deterministicSha256": "sha256:"
        + hashlib.sha256(canonical(core).encode("utf-8")).hexdigest(),
        "environment": {
            "akcCommit": AKC_COMMIT,
            "interpreter": sys.executable,
            "pythonVersion": platform.python_version(),
            "platform": platform.platform(),
            "command": "python research/explore_change_receipt_20260905/build_receipt.py",
            "note": (
                "Recorded for provenance and deliberately outside the digest above: "
                "an interpreter path is a property of the machine, not of the compile."
            ),
        },
    }


def main() -> int:
    receipt = build()
    RECEIPT.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    core = receipt["deterministic"]
    print(f"status: {core['status']}")
    for gap in core["blockedBy"]:
        print(f"  gap {gap['gap']}: {gap['function']}")
    for run in core["runs"]:
        print(f"  run {run['run']}: {run['outcome']}")
    print(f"wrote {RECEIPT}")
    print(f"deterministic sha256 {receipt['deterministicSha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
