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
only from printed clause numbers under printed numbered headings. Run 1 compiles
the revision-B world -- three documents, ten regions -- and every one of those
regions resolves to `UNNUMBERED_PARAGRAPH` / `UNRESOLVED_SOURCE_FACT`; the same
run then hands `resolve_sources` all four fixture documents at once, fourteen
regions, and nothing survives that either. `CORE_V3_NO_RESOLVABLE_UNIT` both
times. Both populations are recorded and both are derived, because a count
printed beside the wrong set is the mistake this lane's prose has now made
twice, and neither time did a green test notice.

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
from akc_cir.revision_compile import (  # noqa: E402
    IdentityContinuity,
    RevisionCompileResult,
    UnitRevisionRecord,
    compile_revision,
)
from akc_core_v3.initial import InitialCompileService  # noqa: E402
from akc_core_v3.resolver import InMemoryWorldArchive, ProductionSourceResolver  # noqa: E402
from akc_core_v3.service import RevisionService  # noqa: E402
from akc_core_v3.sources import (  # noqa: E402
    SourceResolutionRefused,
    canonicalise_document,
    load_document,
    resolve_sources,
)

__all__ = [
    "build",
    "document_reference",
    "input_manifest",
    "main",
    "ocr_record",
    "readme_assertions",
]

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


def _whole_fixture_refusal(entries: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Hand `resolve_sources` all four fixture documents at once, and record it.

    The compile above is a *world*, so it takes three documents: a revision-B
    world does not contain revision C. That makes its ten regions the wrong
    denominator for any sentence about "the four documents", which is exactly
    the sentence this README kept writing. So the wider population is measured
    here instead of inferred: same resolver, same corpus, all four documents,
    fourteen regions, and whatever comes back comes back.
    """
    corpus = Corpus({entry["ocrJsonKey"]: ocr_record(entry) for entry in entries.values()})
    documents = [
        document_reference(
            entry,
            native_id=str(entry["documentId"]),
            title=str(entry["documentId"]),
        )
        for entry in entries.values()
    ]
    ledger = _fact_ledger(corpus, documents)
    refusal: str | None = None
    resolved_units = 0
    try:
        resolved = resolve_sources(corpus, documents)
    except SourceResolutionRefused as refused:
        refusal = refused.code
    else:
        resolved_units = len(resolved.units)
    return {
        "question": (
            "and if the resolver is handed the whole fixture at once rather than one "
            "world's worth of it, does anything survive"
        ),
        "documentIds": sorted(str(entry["documentId"]) for entry in entries.values()),
        "documentsSeen": len(documents),
        "regionsSeen": sum(int(item["regions"]) for item in ledger),
        "unitsResolved": resolved_units,
        "unitsCanonicalised": sum(int(item["units"]) for item in ledger),
        "outcome": "refused" if refusal else "resolved",
        "refusalCode": refusal,
        "sourceFactLedger": ledger,
    }


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
        "documentsCompiled": len(documents),
        "population": (
            "the three documents of the revision-B world: the revision-B manual and "
            "the two the site publishes unchanged. The revision-C manual is not in "
            "this world and its regions are NOT in regionsSeen -- see "
            "wholeFixtureResolverCheck for the four-document number."
        ),
        "sourceFactLedger": ledger,
        "wholeFixtureResolverCheck": _whole_fixture_refusal(entries),
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


def _identity_breakdown(records: Sequence[UnitRevisionRecord]) -> dict[str, Any]:
    """Split the `continued` tally by whether a predecessor was actually recorded.

    `IdentityContinuity.CONTINUED` is the *else* branch of
    `akc_cir.revision_compile._unit_records` (revision_compile.py:876-882): an
    after-unit the diff did not name as added and did not leave unsettled gets
    the label whether or not a predecessor was found for it.
    `previousLogicalUnitId` and `identityRelation` are then filled only when the
    after-unit's OWN logical id is present in the before world
    (revision_compile.py:883-897), so a unit the resolver matched *across* a
    document-id change is labelled `continued` and carries neither field.

    The bare count is therefore not a count of matches, and reading it as one is
    wrong in exactly the case gap F2 is about. This block exists so it cannot be
    read that way again: an earlier revision of this receipt described F2 from
    the label alone and said the opposite of what the run shows.
    """
    continued = [unit for unit in records if unit.continuity is IdentityContinuity.CONTINUED]
    with_predecessor = sorted(
        unit.logical_unit_id for unit in continued if unit.previous_logical_unit_id
    )
    without = sorted(
        unit.logical_unit_id for unit in continued if not unit.previous_logical_unit_id
    )
    return {
        "continued": len(continued),
        "continuedWithRecordedPredecessor": len(with_predecessor),
        "continuedWithoutRecordedPredecessor": len(without),
        "continuedWithoutRecordedPredecessorIds": without,
        "note": (
            "`continued` is a label, not a match count. A unit here with no "
            "previousLogicalUnitId was matched by the resolver or not -- this "
            "field cannot say which, and diffChanges is where to look."
        ),
    }


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
    it, the manual keeps one id across both revisions; without it, revision C
    carries the id its filename implies. Both are run rather than argued, and
    what the second one costs is measured in the records rather than predicted
    here -- an earlier revision of this docstring said "every unit of the manual
    is new", and the run says otherwise.
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
            # `identityCounts` above is a tally of labels. This is the split that
            # says how many of them have a predecessor behind them, and it is
            # what F2 turns on.
            "identityContinuity": _identity_breakdown(result.units),
            # The diff, serialised by the core rather than summarised here. It is
            # the only place the correspondence the resolver made is visible: a
            # change attributed to a BEFORE logical id is a match across the id
            # change, and an unmatched after-unit would appear as `unit_added`
            # instead (semantic_diff.py:809-822).
            "diffChanges": [change.as_record() for change in result.diff.changes],
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


def _matched_across_the_id_change(run: Mapping[str, Any]) -> list[str]:
    """The before-world ids the diff attributed a change of the after world to.

    A change whose `logical_id` belongs to the BEFORE world is a correspondence
    the resolver made: the emitting branch reaches it only after
    `by_logical[decision.logical_id]` resolved to a prior unit
    (semantic_diff.py:815-822). An after-unit with no counterpart leaves by the
    two `UNIT_ADDED` exits above it instead. So this list is the machine-readable
    answer to "did identity survive the document-id change", and it is derived
    from the diff rather than from the `continued` label, which cannot say.
    """
    after = {unit["logicalUnitId"] for unit in run["revision"]["units"]}
    return sorted(
        {
            str(change["logical_id"])
            for change in run["revision"]["diffChanges"]
            if change.get("logical_id") and change["logical_id"] not in after
        }
    )


def _f1_observed_state(site: Mapping[str, Any]) -> str:
    """F1's outcome, with each count beside the set it was counted over.

    Two populations, because there are two and conflating them is how the
    founder-facing sentence went wrong: the compile is a world (three documents)
    and the resolver check is the whole fixture (four). Neither number is typed.
    """
    whole = site["wholeFixtureResolverCheck"]
    kinds = sorted(
        {
            str(fact["kind"])
            for document in whole["sourceFactLedger"]
            for fact in document["facts"]
        }
    )
    states = sorted(
        {
            str(fact["state"])
            for document in whole["sourceFactLedger"]
            for fact in document["facts"]
        }
    )
    return (
        f"{' / '.join(states)} with kind {' / '.join(kinds)} on every region, in both "
        f"populations. The revision-B world compiles {site['documentsCompiled']} "
        f"documents and {site['regionsSeen']} regions: "
        f"{site['unitsResolved']} units out, refused with {site['refusalCode']}. "
        f"Handing resolve_sources the whole fixture instead -- "
        f"{whole['documentsSeen']} documents, {whole['regionsSeen']} regions, the "
        f"revision-C manual included -- resolves {whole['unitsCanonicalised']} units "
        f"and refuses with {whole['refusalCode']}. The four-document figure is the "
        "one to quote for the corpus; the three-document one is what run 1 compiled."
    )


def _f2_observed_state(shared: Mapping[str, Any], split: Mapping[str, Any]) -> str:
    """F2's finding, formatted from the two runs rather than typed beside them.

    The first version of this receipt carried a hand-written sentence here that
    the block underneath it refuted -- it said no unit continues, while
    `identityCounts.continued` read 9. Deriving the sentence is the repair: the
    prose cannot drift from the measurement if the measurement writes it.
    """
    shared_identity = shared["revision"]["identityContinuity"]
    split_identity = split["revision"]["identityContinuity"]
    changes = split["revision"]["diffChanges"]
    cross = _matched_across_the_id_change(split)
    added = [change for change in changes if change["kind"] == "unit_added"]
    # Every clause below is derived, and the two the sentence leans hardest on
    # are asserted rather than trusted: if the resolver ever stops matching here,
    # this function must fail rather than keep printing that it matched.
    assert cross, "no change was attributed to a before-world id"
    assert not added, f"the diff reported {len(added)} unit_added change(s)"
    candidates = sorted(
        {
            candidate
            for change in changes
            if change["kind"] == "identity_unresolved"
            for candidate in change.get("candidates", [])
        }
    )
    missing = split["equivalence"]["missing_from_selective"]
    return (
        "measured in runs[1] against runs[2], which differ in the document id and "
        "in nothing else. The resolver's match survives the id change; nothing "
        "keyed by the id does. (1) The correspondence was made: "
        "runs[2].revision.diffChanges attributes changes of the revision-C manual "
        f"to {len(cross)} revision-B logical ids ({', '.join(cross)}) and names "
        f"{', '.join(candidates)} as the identity candidate for the remaining "
        "revision-C unit, and no unit_added is emitted anywhere in the run -- an "
        "unmatched after-unit would leave by that exit "
        "(semantic_diff.py:809-822). (2) The record cannot express it: "
        f"revision.identityCounts.continued reads {shared_identity['continued']} "
        "in BOTH runs and is not a match count. In runs[1] "
        f"{shared_identity['continuedWithRecordedPredecessor']} of "
        f"{shared_identity['continued']} carry a previousLogicalUnitId and "
        f"SAME_AS_VERSION; in runs[2] only "
        f"{split_identity['continuedWithRecordedPredecessor']} do, and "
        f"{split_identity['continuedWithoutRecordedPredecessor']} carry neither "
        f"({', '.join(split_identity['continuedWithoutRecordedPredecessorIds'])}), "
        "because revision_compile._unit_records looks the predecessor up by the "
        "after-unit's own logical id (revision_compile.py:883). See finding F5. "
        "(3) Nothing downstream of the id survives: the changes name ids that are "
        "not nodes of the after world's dependency graph, so "
        "plan.facetResolutions returns verdict 'unresolved' with that reason, "
        f"impact.affectedArtifactIds is {split['revision']['impact']['affectedArtifactIds']}, "
        f"plan.stale is {split['plan']['stale']}, the selective rebuild never "
        f"builds the {len(missing)} manual artifacts a full rebuild produces "
        "(equivalence.missing_from_selective), and collection:directory is "
        "carried forward stale and diverges."
    )


def canonical(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def deterministic() -> dict[str, Any]:
    """Everything the chain produced. Byte-stable across runs and machines."""
    runs = [
        run_site_fixture_verbatim(),
        run_clause_form(shared_document_id=True),
        run_clause_form(shared_document_id=False),
    ]
    site, shared_id, split_id = runs
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
                "observedState": _f1_observed_state(site),
                "refusal": "CORE_V3_NO_RESOLVABLE_UNIT raised by resolve_sources",
                "evidence": (
                    "runs[0] for the three-document world, "
                    "runs[0].wholeFixtureResolverCheck for all four"
                ),
            },
            {
                "id": "F2",
                "gap": "document-identity-across-revisions",
                "function": "akc_core_v3.sources.canonicalise_document",
                "file": "services/core-v3/src/akc_core_v3/sources.py:498 "
                "-- logical_id = ku_{document_id}_{clause}",
                "requiredInputShape": (
                    "one nativeId for the manual with two contentSha256 versions; "
                    "logical_id is ku_{document_id}_{clause}, and every artifact id, "
                    "dependency-graph node and impact seed is built from the logical id "
                    "in turn, so the document id is what carries a unit's identity "
                    "across a revision everywhere below the resolver"
                ),
                "actualInputShape": (
                    "the site publishes revision B and revision C as two files whose "
                    "documentIds differ (fp200-maintenance-manual-rev-b / -rev-c)"
                ),
                "observedState": _f2_observed_state(shared_id, split_id),
                "refusal": None,
                "evidence": (
                    "runs[1] versus runs[2]; specifically their revision.diffChanges, "
                    "revision.identityContinuity, plan.facetResolutions and "
                    "equivalence.missing_from_selective"
                ),
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
            {
                "id": "F5",
                "kind": "correctness",
                "severity": "medium",
                "title": (
                    "a unit the resolver matched across a document-id change is "
                    "recorded 'continued' with no predecessor and no relation: the "
                    "record looks the predecessor up by the after-unit's own logical "
                    "id, so a lineage that was established is not written down"
                ),
                "where": [
                    "packages/cir-python/src/akc_cir/revision_compile.py:876-882 "
                    "-- the continuity label is the else branch: an after-unit that is "
                    "neither unresolved nor added is CONTINUED, found predecessor or "
                    "not",
                    "packages/cir-python/src/akc_cir/revision_compile.py:883 "
                    "-- prior = before_by_id.get(logical_id), where logical_id is the "
                    "AFTER unit's id and before_by_id is keyed by the BEFORE units' ids",
                    "packages/cir-python/src/akc_cir/revision_compile.py:888-897 "
                    "-- previousLogicalUnitId and SAME_AS_VERSION are emitted only when "
                    "that lookup hits, so a cross-id match yields neither; the "
                    "decision's own matched id, which the diff still carries, is not "
                    "consulted",
                ],
                "measured": (
                    "runs[2].revision.diffChanges shows the match was made -- three "
                    "changes of the revision-C manual are attributed to revision-B "
                    "logical ids and no unit_added is emitted -- while "
                    "runs[2].revision.identityContinuity records 3 of 9 continued units "
                    "with no previousLogicalUnitId. runs[1], where the ids are shared, "
                    "records 9 of 9 with one. The two runs differ in the document id "
                    "and in nothing else."
                ),
                "consequence": (
                    "any consumer reading the unit records -- an earlier revision of "
                    "this very receipt included -- cannot tell a matched continuation "
                    "from an unmatched one, and 'continued: 9' reads as nine matches in "
                    "both runs. That is how the first version of F2 came to state the "
                    "opposite of its own data."
                ),
                "notFixedHere": (
                    "akc_cir.revision_compile is not named in CLAUDE.md's Protected "
                    "Core list, but it composes four modules that are (identity, "
                    "semantic_diff, dependency, recompilation) and it belongs to no "
                    "lane in this campaign. Carrying the decision's matched id into the "
                    "record changes what every revision receipt says about lineage. "
                    "Reported, not touched."
                ),
            },
        ],
        "protectedCoreModified": False,
        "coreFilesModified": [],
        "inputs": input_manifest(),
        "runs": runs,
        "siteFixtureUnitsResolved": site["unitsResolved"],
    }


def readme_assertions(core: Mapping[str, Any]) -> dict[str, str]:
    """Fragments the README must contain verbatim, each derived from a run.

    The README is the only file a founder actually reads, and it is where every
    one of this lane's false statements has landed: round 1 put a retracted
    conclusion in it, round 2 a stale digest, round 3 a count beside the wrong
    population. The receipt's own prose was made underivable-by-hand in round 2
    and stopped drifting; the README was not, and drifted again.

    So the load-bearing counts are generated here and `test_the_readme_carries_
    the_populations_the_runs_measured` asserts each string is present. A README
    that renames a denominator now fails a test instead of shipping. This is not
    a spell-checker: only figures whose wrong version would mislead are listed.
    """
    site = core["runs"][0]
    whole = site["wholeFixtureResolverCheck"]
    return {
        # The exact conflation the round-2 review caught: 10 regions belong to
        # the 3-document world, not to the 4-document fixture.
        "compiled_population": (
            f"{site['regionsSeen']} regions of the {site['documentsCompiled']} documents"
        ),
        "whole_fixture_population": (
            f"{whole['regionsSeen']} regions of the {whole['documentsSeen']} documents"
        ),
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
    # `newline="\n"` rather than the platform default. `.gitattributes` normalises
    # this file to LF, so a Windows run that wrote CRLF would leave the tree dirty
    # on every regeneration and make "the receipt is unchanged" unreadable as a
    # signal. The digest is over the canonical JSON and not the file bytes, so
    # this is about the diff, not about the hash.
    RECEIPT.write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
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
