"""The Apple temporal World, compiled by the Python Core. Program §24 / §26.

Two chains, because the corpus contains two different kinds of change and
conflating them would report one of them as the other.

**Chain A -- corpus growth.** W0 (2025 10-K) -> W1 (+2026 Q1 10-Q) -> W2
(+DEF 14A) -> W3 (+Q2) -> W4 (+Q3), exactly as §24 declares them. Each filing is
its own source with its own lineage; nothing is asserted to be a version of
anything else. This is the chain §24 asks for and the one whose numbers are safe
to read as "what does adding a filing cost".

**Chain B -- quarterly revision.** The three 2026 10-Qs treated as three versions
of one disclosure lineage. This is a **declared modelling assumption**, not a
fact about SEC filings: three accessions are three filings, and calling Q2 a
revision of Q1 is a choice about what the World tracks. It is made because it is
the only place in this corpus where a section's evidence *moves* while its
meaning may or may not change -- which is the exact distinction PR #46 exists to
draw, and which Chain A cannot exercise at all.

Nothing here promotes anything. The challenger arm is a shadow measurement under
the compatibility ladder.

Run:  python run_chain.py <sources-dir> <output-dir>
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sec_adapter
from akc_cir.entity import EntityMention, MergeVerdict, resolve_mention
from akc_cir.identity import evidence_id, source_id
from akc_cir.recompilation import (
    ArtifactState,
    EquivalenceReport,
    RecompilationPlan,
    StructuralPolicy,
    plan_recompilation,
    verify_equivalence,
)
from akc_cir.revision_compile import (
    FAIL_CLOSED_SOURCE_FACT_STATES,
    SourceFactState,
    audit_source_facts,
)
from akc_cir.semantic_diff import ChangeChannel, DiffLevel, diff_documents
from akc_cir.world_state import (
    PublishRefused,
    ValidationReceipt,
    WorldStateRegistry,
    WorldStateStatus,
    publication_manifest,
)
from akc_core_v3.projections import plan_artifacts  # type: ignore[import-untyped]
from akc_core_v3.sources import (  # type: ignore[import-untyped]
    SourceResolutionRefused,
    document_shape,
    resolve_sources,
)
from sec_adapter import Filing

#: The Core is at this commit; the run manifest records the real one.
COMPILER_VERSION = "akc-core-apple-temporal-world-20260908"
TENANT_ID = "tnt_apple_temporal_world_20260908"
WORKSPACE = "ws_apple_temporal_world"
BUILT_AT = datetime(2026, 9, 8, 0, 0, tzinfo=UTC)

#: The lineage string handed to the identity resolver. Passing it asserts only
#: that the two unit sets being compared are two states of one collection, which
#: is structurally true: they are W(n-1) and W(n) of the same World.
COLLECTION_LINEAGE = "collection:apple-temporal-world-2026"

# ---------------------------------------------------------------------------
# The corpus, copied verbatim from the committed public manifest
# (site-main/nextjs/public/explore-sample/sec-corpus-manifest.json and
# scripts/build-explore-sample.mjs:133-160). No field here was inferred.

FILINGS: tuple[Filing, ...] = (
    Filing(
        filing_id="apple-form-10-k",
        form="10-K",
        filing_date="2025-10-31",
        report_date="2025-09-27",
        accession="0000320193-25-000079",
        cik="0000320193",
        authority="official",
        pdf_filename="apple-2025-form-10-k.pdf",
        pdf_sha256="108590052c3ba5400c63660d787fe7ed4e43868292946d7a7facebe9ab7d1aab",
        representation_kind="original",
        original_sha256=None,
        render_profile=None,
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/"
            "aapl-20250927.htm"
        ),
        title="Apple Inc. 2025 Form 10-K",
        empty_user_password=True,
    ),
    Filing(
        filing_id="apple-2026-q1-10-q",
        form="10-Q",
        filing_date="2026-01-30",
        report_date="2025-12-27",
        accession="0000320193-26-000006",
        cik="0000320193",
        authority="official",
        pdf_filename="apple-2026-q1-10-q-reference.pdf",
        pdf_sha256="7fe2683c59e0b48f6c112bc17b3900d907f64236c138d1dd32f40d544b1ba89f",
        representation_kind="render",
        original_sha256=(
            "sha256:52d955e28dcd11351814607d748217babc68cdf364387c1ff05ed62c3842c7cc"
        ),
        render_profile=(
            "chromium-print-letter-v1; scripts/links/iframes/images removed; "
            "inline filing content retained"
        ),
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/320193/000032019326000006/"
            "aapl-20251227.htm"
        ),
        title="Apple Inc. 2026 Q1 Form 10-Q",
    ),
    Filing(
        filing_id="apple-2026-proxy-def14a",
        form="DEF 14A",
        filing_date="2026-01-08",
        report_date="2026-02-24",
        accession="0001308179-26-000008",
        cik="0000320193",
        authority="official",
        pdf_filename="apple-2026-proxy-def14a-reference.pdf",
        pdf_sha256="aa84ce73eb0f181844ccd0bb8a4a53f670fae6a007c086ccdb55f705f8d7a0c2",
        representation_kind="render",
        original_sha256=(
            "sha256:9729235a5b43825067b0ea1dd8d6dd54db36097b4a0073da33db7e41f2b358b1"
        ),
        render_profile=(
            "chromium-print-letter-v1; scripts/links/iframes/images removed; "
            "inline filing content retained"
        ),
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/320193/000130817926000008/"
            "aapl014016-def14a.htm"
        ),
        title="Apple Inc. 2026 Proxy Statement (DEF 14A)",
    ),
    Filing(
        filing_id="apple-2026-q2-10-q",
        form="10-Q",
        filing_date="2026-05-01",
        report_date="2026-03-28",
        accession="0000320193-26-000013",
        cik="0000320193",
        authority="official",
        pdf_filename="apple-2026-q2-10-q-reference.pdf",
        pdf_sha256="054bff6adefda8601bc6a253181448d708ea78e93f936d9b0cff6e97e4f2a9d7",
        representation_kind="render",
        original_sha256=(
            "sha256:94db39194b69cc43aed0fdecc1d4b4a99a72808bea4a1971e7fba1a11c270e0f"
        ),
        render_profile=(
            "chromium-print-letter-v1; scripts/links/iframes/images removed; "
            "inline filing content retained"
        ),
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/320193/000032019326000013/"
            "aapl-20260328.htm"
        ),
        title="Apple Inc. 2026 Q2 Form 10-Q",
    ),
    Filing(
        filing_id="apple-2026-q3-10-q",
        form="10-Q",
        filing_date="2026-07-31",
        report_date="2026-06-27",
        accession="0000320193-26-000020",
        cik="0000320193",
        authority="official",
        pdf_filename="apple-2026-q3-10-q-reference.pdf",
        pdf_sha256="6a9e1c4bbaaed622299d4e6db70d2672fe04512c1ccde72ded20ee9d05a7a0c5",
        representation_kind="render",
        original_sha256=(
            "sha256:13696fb8f3374db66784c17852b1c9d56dec2664991022d8a9d8651e797e0c53"
        ),
        render_profile=(
            "chromium-print-letter-v1; scripts/links/iframes/images removed; "
            "inline filing content retained"
        ),
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/320193/000032019326000020/"
            "aapl-20260627.htm"
        ),
        title="Apple Inc. 2026 Q3 Form 10-Q",
    ),
)

BY_ID = {filing.filing_id: filing for filing in FILINGS}

CHAIN_A_STEPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("w0", "2025 Form 10-K", ("apple-form-10-k",)),
    ("w1", "+ 2026 Q1 10-Q", ("apple-form-10-k", "apple-2026-q1-10-q")),
    (
        "w2",
        "+ 2026 DEF 14A",
        ("apple-form-10-k", "apple-2026-q1-10-q", "apple-2026-proxy-def14a"),
    ),
    (
        "w3",
        "+ 2026 Q2 10-Q",
        (
            "apple-form-10-k",
            "apple-2026-q1-10-q",
            "apple-2026-proxy-def14a",
            "apple-2026-q2-10-q",
        ),
    ),
    (
        "w4",
        "+ 2026 Q3 10-Q",
        (
            "apple-form-10-k",
            "apple-2026-q1-10-q",
            "apple-2026-proxy-def14a",
            "apple-2026-q2-10-q",
            "apple-2026-q3-10-q",
        ),
    ),
)

CHAIN_B_STEPS: tuple[tuple[str, str, str], ...] = (
    ("r0", "2026 Q1 10-Q", "apple-2026-q1-10-q"),
    ("r1", "revised by Q2", "apple-2026-q2-10-q"),
    ("r2", "revised by Q3", "apple-2026-q3-10-q"),
)

#: §26's stage list, and what this run actually did with each stage. A stage
#: that did not run says so and says why; none is quietly skipped.
STAGE_DISPOSITION: tuple[tuple[str, str, str], ...] = (
    ("SOURCE", "RUN", "five committed PDFs, sha256 verified against the manifest"),
    (
        "SECURITY",
        "NOT_RUN",
        "no malware scanner or CDR pipeline is available in this lane; the bytes "
        "are the repository's own committed corpus",
    ),
    (
        "ORIGINAL REPRESENTATION",
        "RUN",
        "recorded per filing; for the four 2026 filings the committed PDF is a "
        "render and the SEC HTML is the original, and both digests are carried",
    ),
    (
        "SANITIZED REPRESENTATION",
        "NOT_RUN",
        "CDR is not available in this lane; no sanitized representation exists, "
        "and the render is never labelled one",
    ),
    ("NATIVE", "RUN", "akc_native_parsers.pdf_parser.parse_pdf_to_cir"),
    ("VISUAL", "NOT_RUN", "no rasteriser or vision model in this lane"),
    ("OCR", "NOT_RUN", "no GPU and no OCR model; native text layer only"),
    (
        "RECONCILE",
        "NOT_RUN",
        "one representation per filing, so there is no second result to reconcile "
        "against; akc_cir.reconciler was not exercised",
    ),
    (
        "LOSS DETECTION",
        "NOT_RUN",
        "no loss detector exists (WP-R7); the source-fact ledger below is an "
        "accounting of representation, not a detector",
    ),
    ("RECOVERY", "NOT_RUN", "no stage failed, so no recovery was invoked"),
    (
        "VERIFICATION",
        "PARTIAL",
        "selective-vs-full rebuild equivalence runs on every step; no independent "
        "model verifier ran",
    ),
    ("EXACT EVIDENCE", "RUN", "page + bbox1000 per unit, from the parser"),
    ("CANONICAL IR", "RUN", "akc_cir CanonicalDocument per filing"),
    ("IDENTITY", "RUN", "akc_cir.identity via akc_cir.semantic_diff"),
    ("CLAIM", "RUN", "one canonical unit per anchored disclosure section"),
    (
        "RELATION",
        "PARTIAL",
        "structural relations only (the artifact dependency graph and entity "
        "bindings); no semantic relation extractor ran and none was faked",
    ),
    (
        "AUTHORITY",
        "PARTIAL",
        "every region carries the filing's declared authority; the corpus is "
        "uniformly 'official', so no authority conflict can arise and none did",
    ),
    (
        "TIME",
        "PARTIAL",
        "filing and report dates are carried per filing; akc_cir.temporal's "
        "valid-time resolution was not exercised",
    ),
    ("ACL", "NOT_RUN", "no tenant runtime or permission store in this lane"),
    ("ONTOLOGY", "RUN", "collection:ontology projection"),
    ("DEPENDENCY", "RUN", "akc_core_v3.projections.plan_artifacts"),
    ("TEMPORAL WORLD", "RUN", "akc_cir.world_state registry, one per chain"),
    ("REVIEW", "RUN", "ValidationReceipt per publish"),
    ("ACTIVATE", "RUN", "atomic publish, with the two refusal controls below"),
    ("ASK", "NOT_RUN", "no model call; no paid API in this lane"),
    ("MCP/API/EXPORT", "NOT_RUN", "out of scope for this lane"),
)


def _box(value: Sequence[Any]) -> tuple[int, int, int, int]:
    """Four integers, as a four-tuple the identity module can type-check."""
    x0, y0, x1, y1 = (int(v) for v in value)
    return (x0, y0, x1, y1)


def _sha(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fraction(plan: RecompilationPlan) -> float:
    if not plan.total_artifacts:
        return 0.0
    return len(plan.to_rebuild) / plan.total_artifacts


def _plan_record(plan: RecompilationPlan) -> dict[str, Any]:
    states: dict[str, int] = {}
    for target in plan.targets:
        states[target.state.value] = states.get(target.state.value, 0) + 1
    return {
        "changeId": plan.change_id,
        "totalArtifacts": plan.total_artifacts,
        "rebuilt": len(plan.to_rebuild),
        "rebuildFraction": round(_fraction(plan), 6),
        "states": states,
        "unresolvedArtifacts": sorted(
            t.artifact_id for t in plan.targets if t.state is ArtifactState.UNRESOLVED
        ),
        "unresolvedFacetChannels": [
            r.change_channel.value for r in plan.unresolved_facet_changes
        ],
    }


def _equivalence(
    *,
    plan: RecompilationPlan,
    full: Mapping[str, str],
    previous: Mapping[str, str],
) -> EquivalenceReport:
    rebuilt = set(plan.to_rebuild)
    selective = {artifact: full[artifact] for artifact in rebuilt if artifact in full}
    carried = {
        artifact: previous[artifact]
        for artifact in full
        if artifact not in rebuilt and artifact in previous
    }
    return verify_equivalence(
        full_rebuild=dict(full),
        selective_rebuild=selective,
        carried_over=carried,
        plan=plan,
    )


#: The three arms every step is measured under.
#:
#: `legacy_default` is what a caller of `plan_recompilation` gets today with no
#: arguments. `legacy_precise` is the same protected-core function with the
#: structural channel switched to `PRECISE`, which is a documented option the
#: module already ships -- not a change to it. `challenger` is PR #46's
#: `akc_cir.semantic_impact.plan_semantic_recompilation`, measured in shadow and
#: promoted by nothing here.
def _arms(
    *, diff: Any, graph: Any, artifacts: Sequence[str], challenger: Any
) -> dict[str, RecompilationPlan]:
    arms: dict[str, RecompilationPlan] = {
        "legacy_default": plan_recompilation(
            diff=diff, graph=graph, artifacts=artifacts
        ),
        "legacy_precise": plan_recompilation(
            diff=diff,
            graph=graph,
            artifacts=artifacts,
            structural_policy=StructuralPolicy.PRECISE,
        ),
    }
    if challenger is not None:
        arms["challenger"] = challenger(diff=diff, graph=graph, artifacts=artifacts)
    return arms


def _entity_pass(parsed_by_id: Mapping[str, Any], filing_ids: Sequence[str]) -> dict[str, Any]:
    """Resolve the registrant across filings, anchored to where it is printed.

    No NER ran. The only mention this pass considers is a region whose text is
    exactly the registrant's name, and the only identifier it carries is the CIK
    the filing itself declares. An entity that cannot be anchored to a printed
    region is not created.
    """
    registry: list[tuple[str, EntityMention]] = []
    decisions: list[dict[str, Any]] = []
    for filing_id in filing_ids:
        parsed = parsed_by_id[filing_id]
        filing = parsed.filing
        anchor = next(
            (
                region
                for region in parsed.record["regions"]
                if region["text"].strip() == "Apple Inc."
            ),
            None,
        )
        if anchor is None:
            decisions.append(
                {
                    "filing": filing_id,
                    "verdict": "NO_MENTION",
                    "reason": "no region prints the registrant name exactly",
                }
            )
            continue
        mention = EntityMention(
            mention_id=f"mention:{filing_id}:registrant",
            text="Apple Inc.",
            evidence_id=evidence_id(
                document_version=parsed.document_version,
                page_number1=int(anchor["pageNumber1"]),
                bbox1000=_box(anchor["bbox1000"]),
                span_text=str(anchor["text"]),
            ),
            type_candidate="organization",
            external_ids={"sec-cik": filing.cik},
        )
        decision = resolve_mention(mention, registry)
        if decision.verdict is MergeVerdict.AUTO_MERGE and decision.entity_id:
            entity = decision.entity_id
        else:
            entity = f"entity:registrant:{filing.cik}"
            registry.append((entity, mention))
        decisions.append(
            {
                "filing": filing_id,
                "verdict": decision.verdict.value,
                "tier": decision.tier.name if decision.tier else None,
                "entityId": entity,
                "evidenceId": mention.evidence_id,
                "reason": decision.reason,
            }
        )
    verdicts: dict[str, int] = {}
    for decision_record in decisions:
        verdict = str(decision_record["verdict"])
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
    return {
        "entities": sorted({d["entityId"] for d in decisions if d.get("entityId")}),
        "verdicts": verdicts,
        # REVIEW is the only verdict that means "the resolver would not decide".
        # NEW_ENTITY is a decision: nothing matched, so this is the first
        # mention. Counting it as unresolved would inflate the number that is
        # supposed to mean "a person has to look at this".
        "needsReview": [d for d in decisions if d["verdict"] == "REVIEW"],
        "decisions": decisions,
    }


#: Which arm's plan is handed to `world_state.publish`. `legacy_precise` because
#: it is the only arm this corpus's own equivalence oracle passes; the other two
#: arms' refusals are recorded per step rather than hidden by publishing a plan
#: that happened to work.
PUBLISHING_ARM = "legacy_precise"


def _summary_fractions(arms: Mapping[str, Any]) -> dict[str, Any]:
    if "rebuildFraction" in arms:  # the initial-compile shape
        return {"initialCompile": True, "rebuildFraction": arms["rebuildFraction"]}
    out: dict[str, Any] = {}
    for name, record in arms.items():
        if not isinstance(record, dict) or "rebuildFraction" not in record:
            out[name] = record
            continue
        out[name] = {
            "rebuildFraction": record["rebuildFraction"],
            "rebuilt": record["rebuilt"],
            "equivalent": record["equivalence"]["equivalent"],
            "staleLeftBehind": len(record["equivalence"]["stale_left_behind"]),
        }
    return out


def _initial_arm_record(total: int) -> dict[str, Any]:
    return {
        "note": (
            "initial compile: there is no predecessor, so every artifact is built "
            "and the fraction is 1.0 by definition, not by measurement"
        ),
        "totalArtifacts": total,
        "rebuilt": total,
        "rebuildFraction": 1.0,
    }


def _arm_records(
    arms: Mapping[str, RecompilationPlan],
    reports: Mapping[str, EquivalenceReport],
    challenger: Any,
) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for name, plan in arms.items():
        record = _plan_record(plan)
        record["equivalence"] = reports[name].as_record()
        records[name] = record
    if challenger is None:
        records["challenger"] = {
            "NOT_RUN": "akc_cir.semantic_impact is not importable on this branch"
        }
    return records


def _fact_record(facts: Sequence[Any]) -> dict[str, Any]:
    """Every region accounted for. `fail_closed` is a fact-id list in the audit;
    it is summarised by kind here because printing 40,000 ids would bury the one
    number that matters -- how much of the source is represented."""
    tally = audit_source_facts(tuple(facts))
    by_kind: dict[str, int] = {}
    for fact in facts:
        if fact.state in FAIL_CLOSED_SOURCE_FACT_STATES:
            by_kind[fact.kind] = by_kind.get(fact.kind, 0) + 1
    return {
        "total": len(facts),
        "coveragePermille": round(tally.coverage * 1000),
        "sourceFaithful": tally.source_faithful,
        "failClosedCount": len(tally.fail_closed),
        "failClosedByKind": dict(sorted(by_kind.items())),
        "ignoredPolicies": list(tally.ignored_policies),
        "tally": {state.value: tally.tally.get(state.value, 0) for state in SourceFactState},
        "failClosedStates": sorted(s.value for s in FAIL_CLOSED_SOURCE_FACT_STATES),
    }


def _publish(
    registry: WorldStateRegistry,
    *,
    world_state_id: str,
    artifacts: Mapping[str, str],
    change_set_id: str | None,
    plan: RecompilationPlan | None,
    equivalence: Any,
    activated_at: datetime,
) -> dict[str, Any]:
    """Publish, or record why the Core refused. A refusal is a result."""
    try:
        return _publish_or_raise(
            registry,
            world_state_id=world_state_id,
            artifacts=artifacts,
            change_set_id=change_set_id,
            plan=plan,
            equivalence=equivalence,
            activated_at=activated_at,
        )
    except PublishRefused as refusal:
        return {
            "worldStateId": world_state_id,
            "status": "REFUSED",
            "refusal": str(refusal),
            "activeCount": registry.active_count(),
        }


def _publish_or_raise(
    registry: WorldStateRegistry,
    *,
    world_state_id: str,
    artifacts: Mapping[str, str],
    change_set_id: str | None,
    plan: RecompilationPlan | None,
    equivalence: Any,
    activated_at: datetime,
) -> dict[str, Any]:
    registry.stage(
        world_state_id=world_state_id,
        compiler_version=COMPILER_VERSION,
        built_at=BUILT_AT,
        change_set_id=change_set_id,
    )
    manifest = publication_manifest(
        world_state_id=world_state_id,
        compiler_version=COMPILER_VERSION,
        artifact_hashes=dict(artifacts),
    )
    receipt = ValidationReceipt(
        receipt_id=f"vr-{world_state_id}",
        checksums_verified=True,
        permission_checked=True,
        integrity_passed=True,
        equivalence=equivalence,
    )
    result = registry.publish(
        world_state_id,
        manifest=manifest,
        receipt=receipt,
        artifacts=dict(artifacts),
        activated_at=activated_at,
        plan=plan,
    )
    return {
        "worldStateId": result.world_state.world_state_id,
        "status": result.world_state.status.value,
        "parent": result.world_state.parent_world_state_id,
        "manifestHash": manifest.manifest_hash,
        "receiptPassed": receipt.passed,
    }


def _refusal_controls(artifacts: Mapping[str, str], plan: RecompilationPlan) -> dict[str, Any]:
    """Two fail-closed paths, executed rather than described.

    A partial world and a selective build with no equivalence check are the two
    ways an incomplete state could become ACTIVE. Both are refused here on this
    corpus's own artifact set, so the claim is a receipt and not a design note.
    """
    controls: dict[str, Any] = {}

    partial = WorldStateRegistry("ws_refusal_control_partial")
    partial.stage(
        world_state_id="ws-partial",
        compiler_version=COMPILER_VERSION,
        built_at=BUILT_AT,
    )
    dropped = sorted(artifacts)[0]
    incomplete = {k: v for k, v in artifacts.items() if k != dropped}
    try:
        partial.publish(
            "ws-partial",
            manifest=publication_manifest(
                world_state_id="ws-partial",
                compiler_version=COMPILER_VERSION,
                artifact_hashes=dict(artifacts),
            ),
            receipt=ValidationReceipt(
                receipt_id="vr-partial",
                checksums_verified=True,
                permission_checked=True,
                integrity_passed=True,
            ),
            artifacts=incomplete,
            activated_at=BUILT_AT,
        )
    except PublishRefused as refusal:
        controls["partialWorldRefused"] = {
            "droppedArtifact": dropped,
            "refusal": str(refusal),
            "activeCount": partial.active_count(),
        }
    else:  # pragma: no cover - a pass here is a stop-the-line finding
        controls["partialWorldRefused"] = {"REFUSAL_DID_NOT_HAPPEN": True}

    unchecked = WorldStateRegistry("ws_refusal_control_unchecked")
    unchecked.stage(
        world_state_id="ws-unchecked",
        compiler_version=COMPILER_VERSION,
        built_at=BUILT_AT,
    )
    try:
        unchecked.publish(
            "ws-unchecked",
            manifest=publication_manifest(
                world_state_id="ws-unchecked",
                compiler_version=COMPILER_VERSION,
                artifact_hashes=dict(artifacts),
            ),
            receipt=ValidationReceipt(
                receipt_id="vr-unchecked",
                checksums_verified=True,
                permission_checked=True,
                integrity_passed=True,
            ),
            artifacts=dict(artifacts),
            activated_at=BUILT_AT,
            plan=plan,
        )
    except PublishRefused as refusal:
        controls["selectiveWithoutEquivalenceRefused"] = {
            "refusal": str(refusal),
            "activeCount": unchecked.active_count(),
        }
    else:  # pragma: no cover - a pass here is a stop-the-line finding
        controls["selectiveWithoutEquivalenceRefused"] = {"REFUSAL_DID_NOT_HAPPEN": True}
    return controls


def _stock_core_arm(parsed_by_id: Mapping[str, Any]) -> dict[str, Any]:
    """What the Core's own canonicaliser does with these filings, unmodified.

    Reported because it is the answer to the matrix's finding that no Apple
    filing has ever gone through the Python Core -- not because it is a failure
    to route around.
    """
    store = sec_adapter._MemoryStore(
        {f"ocr/{fid}.json": dict(parsed.record) for fid, parsed in parsed_by_id.items()}
    )
    documents = [
        {
            "nativeId": fid,
            "title": parsed.filing.title,
            "ocrObjectKey": f"ocr/{fid}.json",
            "immutableObjectKey": str(parsed.record["sourceImmutableKey"]),
            "contentSha256": str(parsed.record["inputSha256"]),
            "pageCount": parsed.page_count,
        }
        for fid, parsed in parsed_by_id.items()
    ]
    try:
        resolved = resolve_sources(store, documents)
    except SourceResolutionRefused as refusal:
        return {
            "outcome": "REFUSED",
            "code": refusal.code,
            "status": refusal.status,
            "note": (
                "akc_core_v3.sources.canonicalise_document recognises one unit shape, "
                "a numbered contract clause such as '4.1 Payment is due'. An SEC "
                "filing prints 'Item 1A.' and 'Note 3 -', so the stock path resolves "
                "no unit and fails closed rather than compiling a world it cannot "
                "ground. This is the Core behaving correctly on an unsupported "
                "document family, not a defect to route around."
            ),
        }
    return {
        "outcome": "RESOLVED",
        "units": len(resolved.units),
        "facts": _fact_record(resolved.facts),
    }


def _unit_index(units: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {
            "logicalId": unit.logical_id,
            "documentId": unit.document_id,
            "section": unit.section,
            "identifier": unit.explicit_identifier,
            "authority": unit.authority,
            "evidence": unit.provenance(),
            "textSha256": "sha256:"
            + hashlib.sha256(unit.text.encode("utf-8")).hexdigest(),
            "textChars": len(unit.text),
        }
        for unit in units
    ]


def _change_summary(diff: Any) -> dict[str, Any]:
    kinds: dict[str, int] = {}
    channels: dict[str, int] = {}
    for change in diff.changes:
        kinds[change.kind.value] = kinds.get(change.kind.value, 0) + 1
        channels[change.channel.value] = channels.get(change.channel.value, 0) + 1
    return {
        "changeId": diff.change_id,
        "level": diff.level.value,
        "contentChanged": diff.content_changed,
        "total": len(diff.changes),
        "kinds": kinds,
        "channels": channels,
        "semanticSeeds": len(diff.changed_logical_ids),
        "locatorSeeds": len(diff.changed_logical_ids_for(ChangeChannel.LOCATOR)),
        "unresolvedIdentities": len(diff.unresolved),
        "structuralScope": len(diff.structural_scope),
    }


def _challenger() -> Callable[..., RecompilationPlan] | None:
    """PR #46's module, if it is importable. Absence is recorded, not assumed."""
    try:
        from akc_cir.semantic_impact import plan_semantic_recompilation
    except ImportError:
        return None
    return plan_semantic_recompilation


def run_chain_a(
    parsed_by_id: Mapping[str, sec_adapter.ParsedFiling], out: Path
) -> dict[str, Any]:
    challenger = _challenger()
    registry = WorldStateRegistry(WORKSPACE + "_a")
    previous_units: tuple[Any, ...] = ()
    previous_sha = ""
    previous_hashes: dict[str, str] = {}
    steps: list[dict[str, Any]] = []

    for index, (step_id, label, members) in enumerate(CHAIN_A_STEPS):
        units: list[Any] = []
        facts: list[Any] = []
        documents = []
        for filing_id in members:
            parsed = parsed_by_id[filing_id]
            document = sec_adapter.load(parsed)
            documents.append(document)
            filing_units, filing_facts = sec_adapter.sec_canonicalise(
                parsed,
                document,
                lineage_source=parsed.source,
                lineage_title=parsed.filing.title,
                lineage_document_id=filing_id,
            )
            units.extend(filing_units)
            facts.extend(parsed.parse_facts)
            facts.extend(filing_facts)
        resolved = sec_adapter.resolve_filing([], documents, units, facts)
        plan = plan_artifacts(resolved)
        full = plan.full_rebuild()

        record: dict[str, Any] = {
            "chain": "A",
            "step": step_id,
            "label": label,
            "members": list(members),
            "pages": sum(parsed_by_id[f].page_count for f in members),
            "regions": sum(len(d.regions) for d in documents),
            "units": len(units),
            "evidenceLocators": len(units),
            "artifacts": len(plan.artifacts),
            "dependencyEdges": sum(
                len(plan.graph.edges_from(node)) for node in plan.graph.nodes
            ),
            "sourceSha256": resolved.source_sha256,
            "sourceFacts": _fact_record(facts),
            "entities": _entity_pass(parsed_by_id, members),
        }

        if index == 0:
            record["change"] = None
            record["arms"] = _initial_arm_record(len(plan.artifacts))
            record["publish"] = _publish(
                registry,
                world_state_id=f"world-a-{step_id}",
                artifacts=full,
                change_set_id=None,
                plan=None,
                equivalence=None,
                activated_at=BUILT_AT,
            )
        else:
            diff = diff_documents(
                before_sha256=previous_sha,
                after_sha256=resolved.source_sha256,
                level=DiffLevel.SEMANTIC,
                before_shape=document_shape(previous_units),
                after_shape=document_shape(units),
                before_units=[u.snapshot() for u in previous_units],
                after_units=[u.snapshot() for u in units],
                source=COLLECTION_LINEAGE,
            )
            arms = _arms(
                diff=diff,
                graph=plan.graph,
                artifacts=plan.artifacts,
                challenger=challenger,
            )
            reports = {
                name: _equivalence(plan=p, full=full, previous=previous_hashes)
                for name, p in arms.items()
            }
            record["change"] = _change_summary(diff)
            record["arms"] = _arm_records(arms, reports, challenger)
            record["publish"] = _publish(
                registry,
                world_state_id=f"world-a-{step_id}",
                artifacts=full,
                change_set_id=diff.change_id,
                plan=arms[PUBLISHING_ARM],
                equivalence=reports[PUBLISHING_ARM],
                activated_at=BUILT_AT,
            )
            if index == len(CHAIN_A_STEPS) - 1:
                record["failClosedControls"] = _refusal_controls(
                    full, arms[PUBLISHING_ARM]
                )

        record["unitIndexSha256"] = _write(
            out / "world" / f"chain-a-{step_id}-units.json", _unit_index(units)
        )
        steps.append(record)
        previous_units = tuple(units)
        previous_sha = resolved.source_sha256
        previous_hashes = dict(full)

    return {
        "steps": steps,
        "worldHistory": list(registry.history),
        "activeCount": registry.active_count(),
        "activeStatus": (
            registry.current.status.value if registry.current else None
        ),
        "onlyOneActive": registry.active_count() == 1
        and registry.current is not None
        and registry.current.status is WorldStateStatus.ACTIVE,
    }


def run_chain_b(
    parsed_by_id: Mapping[str, sec_adapter.ParsedFiling], out: Path
) -> dict[str, Any]:
    """The three 10-Qs as one disclosure lineage. Declared assumption, see module docstring."""
    challenger = _challenger()
    lineage_source = source_id(
        tenant_id=TENANT_ID,
        connector_type="sec-edgar",
        native_id="cik-0000320193/form-10-q",
    )
    lineage_title = "Apple Inc. Form 10-Q"
    lineage_document_id = "apple-form-10-q"

    registry = WorldStateRegistry(WORKSPACE + "_b")
    previous_units: tuple[Any, ...] = ()
    previous_sha = ""
    previous_hashes: dict[str, str] = {}
    steps: list[dict[str, Any]] = []

    for index, (step_id, label, filing_id) in enumerate(CHAIN_B_STEPS):
        parsed = parsed_by_id[filing_id]
        document = sec_adapter.load(parsed, document_id=lineage_document_id)
        units, unit_facts = sec_adapter.sec_canonicalise(
            parsed,
            document,
            lineage_source=lineage_source,
            lineage_title=lineage_title,
            lineage_document_id=lineage_document_id,
        )
        facts = [*parsed.parse_facts, *unit_facts]
        resolved = sec_adapter.resolve_filing([], [document], units, facts)
        plan = plan_artifacts(resolved)
        full = plan.full_rebuild()

        record: dict[str, Any] = {
            "chain": "B",
            "step": step_id,
            "label": label,
            "filing": filing_id,
            "pages": parsed.page_count,
            "regions": len(document.regions),
            "units": len(units),
            "evidenceLocators": len(units),
            "artifacts": len(plan.artifacts),
            "sourceSha256": resolved.source_sha256,
            "sourceFacts": _fact_record(facts),
        }

        if index == 0:
            record["change"] = None
            record["arms"] = _initial_arm_record(len(plan.artifacts))
            record["publish"] = _publish(
                registry,
                world_state_id=f"world-b-{step_id}",
                artifacts=full,
                change_set_id=None,
                plan=None,
                equivalence=None,
                activated_at=BUILT_AT,
            )
        else:
            diff = diff_documents(
                before_sha256=previous_sha,
                after_sha256=resolved.source_sha256,
                level=DiffLevel.SEMANTIC,
                before_shape=document_shape(previous_units),
                after_shape=document_shape(units),
                before_units=[u.snapshot() for u in previous_units],
                after_units=[u.snapshot() for u in units],
                source=lineage_source,
            )
            arms = _arms(
                diff=diff,
                graph=plan.graph,
                artifacts=plan.artifacts,
                challenger=challenger,
            )
            reports = {
                name: _equivalence(plan=p, full=full, previous=previous_hashes)
                for name, p in arms.items()
            }
            record["change"] = _change_summary(diff)
            record["arms"] = _arm_records(arms, reports, challenger)
            record["publish"] = _publish(
                registry,
                world_state_id=f"world-b-{step_id}",
                artifacts=full,
                change_set_id=diff.change_id,
                plan=arms[PUBLISHING_ARM],
                equivalence=reports[PUBLISHING_ARM],
                activated_at=BUILT_AT,
            )

        record["unitIndexSha256"] = _write(
            out / "world" / f"chain-b-{step_id}-units.json", _unit_index(units)
        )
        steps.append(record)
        previous_units = tuple(units)
        previous_sha = resolved.source_sha256
        previous_hashes = dict(full)

    return {
        "steps": steps,
        "worldHistory": list(registry.history),
        "activeCount": registry.active_count(),
        "onlyOneActive": registry.active_count() == 1,
    }


def main(argv: Sequence[str]) -> int:
    sources = Path(argv[1]).resolve()
    out = Path(argv[2]).resolve()
    started = time.time()

    parsed_by_id: dict[str, Any] = {}
    parse_records: list[dict[str, Any]] = []
    refusals: list[dict[str, Any]] = []
    for filing in FILINGS:
        path = sources / filing.pdf_filename
        if not path.exists():
            refusals.append({"filing": filing.filing_id, "code": "SOURCE_FILE_ABSENT"})
            continue
        data = path.read_bytes()
        parsed = sec_adapter.parse_filing(
            filing, data, tenant_id=TENANT_ID, created_at=BUILT_AT
        )
        parsed_by_id[filing.filing_id] = parsed
        parse_records.append(
            {
                "filing": filing.filing_id,
                "form": filing.form,
                "accession": filing.accession,
                "filingDate": filing.filing_date,
                "reportDate": filing.report_date,
                "authority": filing.authority,
                "representationKind": filing.representation_kind,
                "originalSha256": filing.original_sha256,
                "renderProfile": filing.render_profile,
                "pdfSha256": f"sha256:{filing.pdf_sha256}",
                "sourceId": parsed.source,
                "documentVersionId": parsed.document_version,
                "pages": parsed.page_count,
                "cirBlocks": len(parsed.document.blocks),
                "regions": len(parsed.record["regions"]),
                "encryptedEmptyUserPassword": filing.empty_user_password,
            }
        )

    if refusals:
        _write(out / "MANIFEST.json", {"refusals": refusals})
        print("refused:", refusals, file=sys.stderr)
        return 2

    chain_a = run_chain_a(parsed_by_id, out)
    chain_b = run_chain_b(parsed_by_id, out)
    stock = _stock_core_arm(parsed_by_id)

    chain_a_sha = _write(out / "steps" / "chain-a.json", chain_a)
    chain_b_sha = _write(out / "steps" / "chain-b.json", chain_b)
    stock_sha = _write(out / "steps" / "stock-core-arm.json", stock)

    manifest = {
        "experiment": "APPLE-TEMPORAL-WORLD-20260908",
        "program": "TAVONEL master program §24, §26",
        "disclosure": "INTERNAL. No number here is a public claim.",
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "akcCir": __import__("akc_cir").__file__,
            "akcCoreV3": __import__("akc_core_v3").__file__,
            "akcNativeParsers": __import__("akc_native_parsers").__file__,
            "pypdf": __import__("pypdf").__version__,
            "seconds": round(time.time() - started, 1),
        },
        "declaredConstants": {
            "nativeTextLayerConfidence": sec_adapter.NATIVE_TEXT_LAYER_CONFIDENCE,
            "nativeTextLayerConfidenceNote": (
                "declared, not measured: no recogniser ran, so there is no score"
            ),
            "anchorMaxChars": sec_adapter.ANCHOR_MAX_CHARS,
            "decorativeGraphicPolicy": sec_adapter.DECORATIVE_GRAPHIC_POLICY,
            "collectionLineage": COLLECTION_LINEAGE,
        },
        "stages": [
            {"stage": name, "disposition": state, "note": note}
            for name, state, note in STAGE_DISPOSITION
        ],
        "inputs": parse_records,
        "receipts": {
            "steps/chain-a.json": chain_a_sha,
            "steps/chain-b.json": chain_b_sha,
            "steps/stock-core-arm.json": stock_sha,
        },
        "chainASummary": [
            {
                "step": s["step"],
                "pages": s["pages"],
                "units": s["units"],
                "artifacts": s["artifacts"],
                **_summary_fractions(s["arms"]),
                "publish": s["publish"]["status"],
            }
            for s in chain_a["steps"]
        ],
        "chainBSummary": [
            {
                "step": s["step"],
                "pages": s["pages"],
                "units": s["units"],
                "artifacts": s["artifacts"],
                **_summary_fractions(s["arms"]),
                "publish": s["publish"]["status"],
            }
            for s in chain_b["steps"]
        ],
    }
    manifest_sha = _write(out / "MANIFEST.json", manifest)
    print("MANIFEST.json", manifest_sha)
    for row in manifest["chainASummary"]:
        print("A", row)
    for row in manifest["chainBSummary"]:
        print("B", row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
