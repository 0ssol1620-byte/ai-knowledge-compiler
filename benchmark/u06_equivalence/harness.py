"""U06 harness: compile revision B cold and incrementally from A, then compare on meaning."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, cast

from akc_product_core import ProductCoreCompiler, ProductCoreCompileRequest
from akc_product_core.contracts import (
    PreviousWorldSnapshot,
    ProductCoreCompileResponse,
    ProductCoreDocument,
    ProductCoreRoute,
)

from benchmark.u06_equivalence.normalize import (
    NormalizationAmbiguous,
    NormalizedWorld,
    normalize,
)

Verdict = Literal["EQUAL", "HOLD", "DIVERGED"]
DEFAULT_RELEASE = "sha256:" + "a" * 64


@dataclass(frozen=True)
class CaseResult:
    verdict: Verdict
    hold_reasons: tuple[str, ...] = ()
    phantom: int = 0
    incremental_status: str = ""
    cold_status: str = ""
    review_reasons: tuple[str, ...] = ()
    # Symmetric differences, incremental-only / cold-only record counts per set.
    only_incremental: dict[str, int] = field(default_factory=dict)
    only_cold: dict[str, int] = field(default_factory=dict)


def _sets(world: NormalizedWorld) -> dict[str, frozenset[str]]:
    return {
        "assertions": world.assertions,
        "entities": world.entities,
        "evidence": world.evidence,
        "edges": world.edges,
    }


def _state_blind(records: frozenset[str]) -> frozenset[str]:
    """Drop verificationState, which legitimately differs between incremental and cold."""
    out = set()
    for record in records:
        data = json.loads(record)
        data.pop("verificationState", None)
        out.add(json.dumps(data, sort_keys=True, ensure_ascii=False))
    return frozenset(out)


def _phantoms(
    incremental: ProductCoreCompileResponse,
    cold: ProductCoreCompileResponse,
    inc_world: NormalizedWorld | None,
    cold_world: NormalizedWorld | None,
) -> int:
    """Facts the incremental world carries that the after-revision does not support."""
    live_versions = {u.source_version_id for u in cold.candidate.units}
    found: set[str] = {
        f"unit:{u.logical_id}"
        for u in incremental.candidate.units
        if u.source_version_id not in live_versions
    }
    for index, obj in enumerate(
        cast(list[dict[str, Any]], incremental.candidate.canonical_knowledge_model["objects"])
    ):
        for ref in obj["sourceRefs"]:
            if ref["documentVersionId"] not in live_versions:
                found.add(f"object:{index}")
    if inc_world is not None and cold_world is not None:
        found |= {f"claim:{k}" for k in inc_world.claim_keys - cold_world.claim_keys}
        # Every object cold does not contain, of any kind; this is the only guard under HOLD.
        for name, records in _sets(inc_world).items():
            extra = _state_blind(records) - _state_blind(_sets(cold_world)[name])
            found |= {f"{name}:{r}" for r in extra}
    return len(found)


def judge(incremental: ProductCoreCompileResponse, cold: ProductCoreCompileResponse) -> CaseResult:
    """Verdict for one incremental/cold pair. HOLD never reads as EQUAL; phantoms count always."""
    reasons: list[str] = []
    if incremental.status == "rejected":
        reasons.append("INCREMENTAL_REJECTED")
    if cold.status == "rejected":
        reasons.append("COLD_REJECTED")
    if incremental.receipt.equivalence == "failed":
        reasons.append("EQUIVALENCE_FAILED")
    if any(u.identity_state == "unresolved" for u in incremental.candidate.units):
        reasons.append("IDENTITY_UNRESOLVED")
    inc_world: NormalizedWorld | None = None
    cold_world: NormalizedWorld | None = None
    try:
        inc_world, cold_world = normalize(incremental), normalize(cold)
    except NormalizationAmbiguous as exc:
        reasons.append("NORMALIZATION_AMBIGUOUS")
        detail = str(exc)
    else:
        detail = ""
    phantom = _phantoms(incremental, cold, inc_world, cold_world)
    only_inc: dict[str, int] = {}
    only_cold: dict[str, int] = {}
    if inc_world is not None and cold_world is not None:
        a, b = _sets(inc_world), _sets(cold_world)
        only_inc = {k: len(a[k] - b[k]) for k in a if a[k] - b[k]}
        only_cold = {k: len(b[k] - a[k]) for k in a if b[k] - a[k]}
    review = incremental.candidate.review_reasons
    if detail:
        review = (*review, f"NORMALIZATION_AMBIGUOUS:{detail}")
    verdict: Verdict
    if reasons:
        verdict = "HOLD"
    elif only_inc or only_cold:
        verdict = "DIVERGED"
    else:
        verdict = "EQUAL"
    return CaseResult(
        verdict=verdict,
        hold_reasons=tuple(reasons),
        phantom=phantom,
        incremental_status=incremental.status,
        cold_status=cold.status,
        review_reasons=review,
        only_incremental=only_inc,
        only_cold=only_cold,
    )


def _request(
    docs: Sequence[ProductCoreDocument],
    *,
    request_id: str,
    requested_at: datetime,
    tenant_id: str,
    workspace_id: str,
    collection_id: str,
    previous: PreviousWorldSnapshot | None = None,
) -> ProductCoreCompileRequest:
    return ProductCoreCompileRequest(
        request_id=request_id,
        idempotency_key=f"idem-{request_id}",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        collection_id=collection_id,
        requested_at=requested_at,
        route=ProductCoreRoute(
            operation_class="incremental_recompile" if previous else "initial_compile",
            quality_requirement="high_assurance",
            max_cost_credits=10,
            max_latency_ms=90_000,
            privacy_policy="foundation_synthetic_only",
        ),
        documents=tuple(docs),
        previous_active_world=previous,
    )


def _digest(request: ProductCoreCompileRequest) -> str:
    return "sha256:" + hashlib.sha256(request.model_dump_json().encode("utf-8")).hexdigest()


def compile_pair(
    before_docs: Sequence[ProductCoreDocument],
    after_docs: Sequence[ProductCoreDocument],
    *,
    requested_at: datetime,
    tenant_id: str = "tenant-foundation-pilot",
    workspace_id: str = "workspace-foundation-pilot",
    collection_id: str = "collection-mixed-corpus",
    core_release_digest: str = DEFAULT_RELEASE,
    tamper_previous: Callable[[PreviousWorldSnapshot], PreviousWorldSnapshot] | None = None,
) -> tuple[ProductCoreCompileResponse, ProductCoreCompileResponse]:
    """Return (incremental, cold) for revision B. `tamper_previous` exists for negative controls."""
    compiler = ProductCoreCompiler(core_release_digest=core_release_digest)
    scope = {
        "requested_at": requested_at,
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "collection_id": collection_id,
    }

    def run(
        docs: Sequence[ProductCoreDocument], rid: str, previous: PreviousWorldSnapshot | None = None
    ) -> ProductCoreCompileResponse:
        request = _request(docs, request_id=rid, previous=previous, **scope)  # type: ignore[arg-type]
        return compiler.compile(request, input_sha256=_digest(request))

    first = run(before_docs, "u06")
    previous = PreviousWorldSnapshot(
        world_state_id=first.candidate.world_state_id,
        manifest_digest=first.candidate.manifest_digest,
        units=first.candidate.units,
        artifact_hashes=first.candidate.artifact_hashes,
    )
    if tamper_previous is not None:
        previous = tamper_previous(previous)
    return run(after_docs, "u06", previous), run(after_docs, "u06")


def run_case(
    before_docs: Sequence[ProductCoreDocument],
    after_docs: Sequence[ProductCoreDocument],
    *,
    requested_at: datetime,
    **kwargs: object,
) -> CaseResult:
    incremental, cold = compile_pair(before_docs, after_docs, requested_at=requested_at, **kwargs)  # type: ignore[arg-type]
    return judge(incremental, cold)
