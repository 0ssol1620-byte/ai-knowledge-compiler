from __future__ import annotations

from datetime import UTC, datetime

from akc_parallel_runtime import (
    CandidateObservation,
    EvidenceReceipt,
    ValidationLevel,
    WorkerSnapshot,
    WorkerState,
    sha256_hex,
)

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
HASH_A = sha256_hex("a")
HASH_B = sha256_hex("b")
HASH_C = sha256_hex("c")
HASH_D = sha256_hex("d")


def receipt(level: ValidationLevel, suffix: str = "ok") -> EvidenceReceipt:
    return EvidenceReceipt(
        source_ref=f"artifact://validation/{level.value}/{suffix}",
        sha256=sha256_hex(f"{level.value}:{suffix}"),
        kind="test_fixture",
    )

def valid_observation(
    *,
    page_ids: tuple[str, ...] = ("p1",),
    levels: tuple[ValidationLevel, ...] = (
        ValidationLevel.TRANSPORT,
        ValidationLevel.STRUCTURAL,
        ValidationLevel.DOWNSTREAM,
    ),
) -> CandidateObservation:
    return CandidateObservation(
        http_status=200,
        response_received=True,
        identity_matches=True,
        checksum_matches=True,
        schema_valid=True,
        size_valid=True,
        finish_reason_complete=True,
        timed_out=False,
        actual_page_ids=page_ids,
        block_count=3,
        bbox_valid=True,
        reading_order_valid=True,
        output_nonempty=True,
        repetition_detected=False,
        source_coverage=1.0,
        native_available=True,
        native_text_coverage=1.0,
        native_numeric_exact=True,
        native_headings_match=True,
        native_object_count_match=True,
        authority_available=True,
        authority_numeric_exact=True,
        authority_period_unit_account_match=True,
        differential_available=True,
        differential_agreement=True,
        expected_invariants_hold=True,
        multimodal_available=True,
        visible_regions_complete=True,
        tables_uncut=True,
        captions_complete=True,
        hierarchy_valid=True,
        downstream_available=True,
        markdown_valid=True,
        package_import_valid=True,
        source_links_valid=True,
        retrieval_valid=True,
        evidence=tuple((level, (receipt(level),)) for level in levels),
    )


def worker(
    worker_id: str = "worker-a",
    *,
    state: WorkerState = WorkerState.HEALTHY,
    model_revision: str = "model@abc123",
    image: str = "sha256:image-a",
    capabilities: frozenset[str] = frozenset({"scan", "table"}),
    warm: bool = True,
    cached: frozenset[str] = frozenset({"model@abc123"}),
    available: float = 0.0,
    score: float = 100.0,
) -> WorkerSnapshot:
    return WorkerSnapshot(
        worker_id=worker_id,
        model_revision=model_revision,
        runtime_image_digest=image,
        state=state,
        capabilities=capabilities,
        warm=warm,
        cached_models=cached,
        estimated_available_at=available,
        semantic_score=score,
    )
