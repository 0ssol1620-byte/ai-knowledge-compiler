"""Canonical v4 collection event names and wire envelope."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, Literal, cast

from pydantic import ConfigDict, Field, field_validator, model_validator

from .base import ContractModel
from .safe_payload import validate_public_payload


class CollectionEventType(StrEnum):
    COLLECTION_CREATED = "collection.created.v1"
    COLLECTION_DISCOVERY_PROGRESS = "collection.discovery.progress.v1"
    COLLECTION_SOURCE_CREATED = "collection.source.created.v1"
    COLLECTION_FILES_PLANNED = "collection.files.planned.v1"
    FILE_DISCOVERED = "file.discovered.v1"
    FILE_HASH_PROGRESS = "file.hash.progress.v1"
    FILE_UPLOAD_PROGRESS = "file.upload.progress.v1"
    FILE_UPLOAD_RESUMED = "file.upload.resumed.v1"
    FILE_UPLOAD_COMPLETED = "file.upload.completed.v1"
    FILE_DUPLICATE_DETECTED = "file.duplicate.detected.v1"
    FILE_SECURITY_PASSED = "file.security.passed.v1"
    COLLECTION_UPLOAD_COMPLETED = "collection.upload.completed.v1"
    COLLECTION_INGESTED = "collection.ingested.v1"
    COLLECTION_PAUSED = "collection.paused.v1"
    COLLECTION_RESUMED = "collection.resumed.v1"
    PREFLIGHT_STARTED = "preflight.started.v1"
    PREFLIGHT_CLUSTER_CREATED = "preflight.cluster.created.v1"
    ESTIMATE_FAST_READY = "estimate.fast.ready.v1"
    ESTIMATE_SAMPLE_UPDATED = "estimate.sample.updated.v1"
    ESTIMATE_FINAL_READY = "estimate.final.ready.v1"
    COLLECTION_PREFLIGHT_COMPLETED = "collection.preflight.completed.v1"
    CREDITS_RESERVED = "credits.reserved.v1"
    PROCESSING_STARTED = "processing.started.v1"
    PROCESSING_SOURCE_EVENTS_BRIDGED = "processing.source_events.bridged.v1"
    PAGE_RENDERED = "page.rendered.v1"
    PAGE_ROUTE_SELECTED = "page.route.selected.v1"
    REGION_DETECTED = "region.detected.v1"
    REGION_ROUTE_SELECTED = "region.route.selected.v1"
    BLOCK_COMPLETED = "block.completed.v1"
    TABLE_RECONSTRUCTED = "table.reconstructed.v1"
    NUMERIC_AUTHORITY_VERIFIED = "numeric.authority.verified.v1"
    VERIFICATION_FAILED = "verification.failed.v1"
    REPAIR_STARTED = "repair.started.v1"
    REPAIR_COMPLETED = "repair.completed.v1"
    OUTPUT_QUARANTINED = "output.quarantined.v1"
    INTEGRITY_DECISION_RECORDED = "integrity.decision.recorded.v1"
    INTEGRITY_ACTION_STATE_CHANGED = "integrity.action.state_changed.v1"
    NOTE_CREATED = "note.created.v1"
    ENTITY_RESOLVED = "entity.resolved.v1"
    RELATION_CREATED = "relation.created.v1"
    ARCHITECTURE_PLAN_CREATED = "architecture.plan.created.v1"
    ARCHITECTURE_FOLDER_CREATED = "architecture.folder.created.v1"
    ARCHITECTURE_MOC_CREATED = "architecture.moc.created.v1"
    ARCHITECTURE_PLAN_COMPILED = "architecture.plan.compiled.v1"
    EXPORT_STARTED = "export.started.v1"
    EXPORT_READY = "export.ready.v1"
    PACKAGE_VALIDATED = "package.validated.v1"
    PACKAGE_SIGNED = "package.signed.v1"
    CREDITS_CONSUMED = "credits.consumed.v1"
    CREDITS_REFUNDED = "credits.refunded.v1"
    CREDITS_RELEASED = "credits.released.v1"
    PROCESSING_PAUSED = "processing.paused.v1"
    PROCESSING_RESUMED = "processing.resumed.v1"
    PROCESSING_RESULT_REUSED = "processing.result.reused.v1"
    PROCESSING_COMPLETED = "processing.completed.v1"
    PROCESSING_FAILED = "processing.failed.v1"
    COLLECTION_EXPORT_COMPLETED = "collection.export.completed.v1"
    COLLECTION_COMPLETED = "collection.completed.v1"
    COLLECTION_DELETION_REQUESTED = "collection.deletion.requested.v1"
    COLLECTION_PURGED = "collection.purged.v1"
    SHARD_PLANNED = "shard.planned.v1"
    SHARD_DISPATCHED = "shard.dispatched.v1"
    ATTEMPT_STARTED = "attempt.started.v1"
    ATTEMPT_OUTPUT_RECEIVED = "attempt.output.received.v1"
    ATTEMPT_VALIDATION_FAILED = "attempt.validation.failed.v1"
    ATTEMPT_ACCEPTED = "attempt.accepted.v1"
    ATTEMPT_REJECTED = "attempt.rejected.v1"
    ATTEMPT_HEDGED = "attempt.hedged.v1"
    WORKER_SEMANTIC_DEGRADED = "worker.semantic.degraded.v1"
    WORKER_DRAINING = "worker.draining.v1"
    WORKER_QUARANTINED = "worker.quarantined.v1"
    RECOVERY_REGION_REQUESTED = "recovery.region.requested.v1"
    RECOVERY_COMPLETED = "recovery.completed.v1"
    CONTINUITY_MERGE_STARTED = "continuity.merge.started.v1"
    CONTINUITY_MERGE_COMPLETED = "continuity.merge.completed.v1"
    DOCUMENT_FINALIZED = "document.finalized.v1"


COLLECTION_EVENT_TYPES: tuple[str, ...] = tuple(item.value for item in CollectionEventType)

PayloadFieldType = type[object] | tuple[type[object], ...]
_NULLABLE_STRING: tuple[type[object], ...] = (str, type(None))


@dataclass(frozen=True)
class CollectionEventPayloadContract:
    required: Mapping[str, PayloadFieldType]
    optional: Mapping[str, PayloadFieldType]


def _contract(
    required: Mapping[str, PayloadFieldType],
    optional: Mapping[str, PayloadFieldType] | None = None,
) -> CollectionEventPayloadContract:
    return CollectionEventPayloadContract(required=dict(required), optional=dict(optional or {}))


COLLECTION_EVENT_PAYLOAD_CONTRACTS: dict[str, CollectionEventPayloadContract] = {
    "collection.created.v1": _contract(
        {"collection_id": str, "project_id": str, "status": str}
    ),
    "collection.discovery.progress.v1": _contract(
        {
            "collection_id": str,
            "source_root_id": str,
            "discovered_files": int,
            "discovered_bytes": int,
            "manifest_revision": int,
        }
    ),
    "collection.source.created.v1": _contract(
        {"collection_id": str, "source_root_id": str, "source_type": str, "status": str}
    ),
    "collection.files.planned.v1": _contract(
        {
            "collection_id": str,
            "source_root_id": str,
            "manifest_revision": int,
            "manifest_sha256": str,
            "total_files": int,
            "total_bytes": int,
            "completed_files": int,
            "active_files": int,
            "failed_files": int,
            "duplicate_files": int,
            "status": str,
        }
    ),
    "file.discovered.v1": _contract(
        {
            "collection_id": str,
            "source_root_id": str,
            "discovered_files": int,
            "discovered_bytes": int,
            "manifest_revision": int,
        }
    ),
    "file.hash.progress.v1": _contract(
        {
            "collection_id": str,
            "hashed_files": int,
            "hash_algorithm": str,
            "quick_fingerprint_files": int,
            "manifest_revision": int,
        }
    ),
    "file.upload.progress.v1": _contract(
        {
            "collection_id": str,
            "upload_session_id": str,
            "completed_files": int,
            "active_files": int,
            "failed_files": int,
            "duplicate_files": int,
        },
        {"manifest_revision": int},
    ),
    "file.upload.resumed.v1": _contract(
        {"collection_id": str, "upload_session_id": str, "resume_version": int},
        {"manifest_revision": int},
    ),
    "file.upload.completed.v1": _contract(
        {
            "collection_id": str,
            "accepted_receipts": int,
            "verified_receipts": int,
            "failed_receipts": int,
            "duplicate_reuses": int,
            "manifest_revision": int,
        }
    ),
    "file.duplicate.detected.v1": _contract(
        {"collection_id": str, "duplicate_files": int, "processing_credits": int}
    ),
    "file.security.passed.v1": _contract(
        {"collection_id": str, "verified_files": int},
        {
            "source_files": int,
            "unavailable_files": int,
            "antivirus_status_counts": dict,
            "cdr_status_counts": dict,
        },
    ),
    "collection.upload.completed.v1": _contract(
        {
            "collection_id": str,
            "upload_session_id": str,
            "manifest_revision": int,
            "manifest_sha256": str,
            "accepted_receipts": int,
            "completed_files": int,
            "active_files": int,
            "failed_files": int,
            "duplicate_files": int,
            "status": str,
        }
    ),
    "collection.ingested.v1": _contract(
        {
            "collection_id": str,
            "verified_files": int,
            "unavailable_files": int,
            "manifest_sha256": str,
            "status": str,
        }
    ),
    "collection.paused.v1": _contract(
        {"collection_id": str, "paused_from": str, "status": str},
        {
            "upload_session_id": str,
            "processing_job_id": str,
            "resume_version": int,
        },
    ),
    "collection.resumed.v1": _contract(
        {"collection_id": str, "resumed_to": str, "status": str},
        {
            "upload_session_id": str,
            "processing_job_id": str,
            "resume_version": int,
        },
    ),
    "preflight.started.v1": _contract(
        {
            "collection_id": str,
            "manifest_revision": int,
            "manifest_sha256": str,
            "status": str,
        }
    ),
    "preflight.cluster.created.v1": _contract(
        {
            "collection_id": str,
            "preflight_id": str,
            "cluster_count": int,
            "member_files": int,
            "feature_records": int,
        }
    ),
    "estimate.fast.ready.v1": _contract(
        {
            "collection_id": str,
            "preflight_id": str,
            "estimate_run_id": str,
            "basis": str,
            "predictor_revision": str,
            "credit_p50": str,
            "credit_p95": str,
            "reserve_ceiling": str,
            "confidence": str,
        }
    ),
    "estimate.sample.updated.v1": _contract(
        {
            "collection_id": str,
            "preflight_id": str,
            "estimate_run_id": str,
            "sampled_pages": int,
            "sample_tiers": list,
            "predictor_revision": str,
        }
    ),
    "estimate.final.ready.v1": _contract(
        {
            "collection_id": str,
            "preflight_id": str,
            "estimate_run_id": str,
            "basis": str,
            "estimate_status": str,
            "credit_p50": str,
            "credit_p95": str,
            "reserve_ceiling": str,
            "confidence": str,
            "predictor_revision": str,
        }
    ),
    "collection.preflight.completed.v1": _contract(
        {
            "collection_id": str,
            "preflight_id": str,
            "manifest_revision": int,
            "manifest_sha256": str,
            "preflight_sha256": str,
            "cluster_count": int,
            "verified_files": int,
            "unavailable_files": int,
            "known_pages": int,
            "estimate_status": str,
            "status": str,
        }
    ),
    "credits.reserved.v1": _contract(
        {"collection_id": str, "processing_job_id": str, "credits": str},
        {"hard_cap": str, "reason": str},
    ),
    "processing.started.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "architecture_plan_id": str,
            "task_count": int,
        },
        {
            "immutable_plan_sha256": str,
            "documents": int,
            "pages": int,
            "processing_jobs": int,
            "execution_scope": str,
            "credits_consumed": int,
            "status": str,
        },
    ),
    "processing.source_events.bridged.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "processing_jobs": int,
            "source_event_count": int,
            "source_event_type_counts": dict,
        }
    ),
    "page.rendered.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "rendered_page_count": int,
            "rendered_asset_count": int,
            "asset_type_counts": dict,
            "asset_set_sha256": str,
        }
    ),
    "page.route.selected.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "page_count": int,
            "route_counts": dict,
            "route_policy_versions": list,
        }
    ),
    "region.detected.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "region_count": int,
            "region_type_counts": dict,
            "evidence": str,
        }
    ),
    "region.route.selected.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "region_attempt_count": int,
            "route_counts": dict,
        }
    ),
    "block.completed.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "block_count": int,
            "block_type_counts": dict,
            "evidence_bound": bool,
        }
    ),
    "table.reconstructed.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "table_count": int,
            "source": str,
        }
    ),
    "numeric.authority.verified.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "matched_authority_mapping_count": int,
        }
    ),
    "verification.failed.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "architecture_plan_id": str,
            "state": str,
            "reason_codes": list,
        }
    ),
    "repair.started.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "repair_id": str,
            "target_type": str,
            "target_id": str,
            "repair_stage": str,
        }
    ),
    "repair.completed.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "repair_id": str,
            "target_type": str,
            "target_id": str,
            "repair_stage": str,
            "result_status": str,
        }
    ),
    "output.quarantined.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "isolated_review_count": int,
            "isolation_status_counts": dict,
            "billing": str,
        }
    ),
    "integrity.decision.recorded.v1": _contract(
        {
            "collection_id": str,
            "decision_id": str,
            "target_type": str,
            "target_id": str,
            "action": str,
            "reason_code": str,
            "result_status": str,
            "evidence_reference_kind": str,
        }
    ),
    "integrity.action.state_changed.v1": _contract(
        {
            "collection_id": str,
            "decision_id": str,
            "execution_id": str,
            "target_type": str,
            "target_id": str,
            "action": str,
            "status": str,
            "execution_receipt_sha256": str,
        },
        {
            "processing_job_id": str,
            "analysis_task_id": str,
            "registry_model_id": str,
            "result_code": str,
        },
    ),
    "note.created.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "note_count": int,
            "evidence_bound": bool,
        }
    ),
    "entity.resolved.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "entity_count": int,
            "scope": str,
        }
    ),
    "relation.created.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "relation_count": int,
            "evidence_bound": bool,
        }
    ),
    "architecture.plan.created.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "architecture_plan_id": str,
            "plan_version": int,
            "integrity_sha256": str,
            "module_count": int,
        }
    ),
    "architecture.folder.created.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "architecture_plan_id": str,
            "folder_count": int,
            "declarative": bool,
        }
    ),
    "architecture.moc.created.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "architecture_plan_id": str,
            "moc_count": int,
            "linked_note_count": int,
        }
    ),
    "architecture.plan.compiled.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "architecture_plan_id": str,
            "plan_version": int,
            "integrity_sha256": str,
            "verified_files": int,
            "documents": int,
            "pages": int,
            "knowledge_notes": int,
            "entities": int,
            "relations": int,
            "autonomously_isolated_legacy_reviews": int,
            "credits_consumed": str,
            "status": str,
        }
    ),
    "export.started.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": _NULLABLE_STRING,
            "export_id": str,
            "package_manifest_id": str,
            "profile": str,
            "completion_scope": str,
            "status": str,
        }
    ),
    "export.ready.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": _NULLABLE_STRING,
            "export_id": str,
            "package_manifest_id": str,
            "package_sha256": str,
            "manifest_sha256": str,
            "size_bytes": int,
            "file_count": int,
            "signature_status": str,
        }
    ),
    "package.validated.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": _NULLABLE_STRING,
            "export_id": str,
            "package_manifest_id": str,
            "package_validation_id": str,
            "validator_version": str,
            "validation_status": str,
            "evidence_sha256": str,
            "external_signer_required": bool,
        }
    ),
    "package.signed.v1": _contract(
        {
            "collection_id": str,
            "export_id": str,
            "package_manifest_id": str,
            "signature_sha256": str,
            "signer_key_id": str,
            "signature_status": str,
        },
        {"processing_job_id": _NULLABLE_STRING},
    ),
    "credits.consumed.v1": _contract(
        {"collection_id": str, "processing_job_id": str, "credits": str},
        {"billable_pages": int},
    ),
    "credits.refunded.v1": _contract(
        {"collection_id": str, "processing_job_id": str, "credits": str, "reason": str}
    ),
    "credits.released.v1": _contract(
        {"collection_id": str, "processing_job_id": str, "credits": str, "reason": str},
        {"cancelled_from": str},
    ),
    "processing.paused.v1": _contract(
        {"collection_id": str, "processing_job_id": str, "queued_tasks_deferred": int}
    ),
    "processing.resumed.v1": _contract(
        {"collection_id": str, "processing_job_id": str},
        {
            "architecture_plan_id": str,
            "resume_version": int,
            "stage": str,
            "package_attempt": int,
            "finalizer_retry_attempt": int,
            "retry_attempt": int,
            "hard_cap": str,
        },
    ),
    "processing.result.reused.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "analysis_task_id": str,
            "billing_owner_job_id": _NULLABLE_STRING,
            "billing_basis_sha256": str,
            "reused_pages": int,
            "credits": str,
        }
    ),
    "processing.completed.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": str,
            "architecture_plan_id": str,
            "package_manifest_id": str,
            "export_id": str,
            "package_sha256": str,
        }
    ),
    "processing.failed.v1": _contract(
        {"collection_id": str, "processing_job_id": str, "error_code": str},
        {
            "completed_tasks": int,
            "failed_tasks": int,
            "billable_pages": int,
            "unbillable_pages": int,
            "partial": bool,
        },
    ),
    "collection.export.completed.v1": _contract(
        {
            "collection_id": str,
            "export_id": str,
            "package_manifest_id": str,
            "profile": str,
            "package_sha256": str,
            "manifest_sha256": str,
            "size_bytes": int,
            "file_count": int,
            "signature_status": str,
            "completion_scope": str,
            "status": str,
        },
        {"processing_job_id": _NULLABLE_STRING},
    ),
    "collection.completed.v1": _contract(
        {
            "collection_id": str,
            "processing_job_id": _NULLABLE_STRING,
            "export_id": str,
            "package_manifest_id": str,
            "profile": str,
            "signature_status": str,
            "status": str,
        }
    ),
    "collection.deletion.requested.v1": _contract(
        {"collection_id": str, "status": str}
    ),
    "collection.purged.v1": _contract(
        {
            "collection_id": str,
            "purged_package_objects": int,
            "shared_source_objects_retained": bool,
            "status": str,
        }
    ),
    "shard.planned.v1": _contract(
        {
            "collection_id": str,
            "document_id": str,
            "shard_id": str,
            "shard_kind": str,
            "page_start": int,
            "page_end": int,
            "route_class": str,
            "shard_state": str,
        }
    ),
    "shard.dispatched.v1": _contract(
        {
            "collection_id": str,
            "document_id": str,
            "shard_id": str,
            "attempt_id": str,
            "pool_key": str,
            "route_class": str,
            "shard_state": str,
        }
    ),
    "attempt.started.v1": _contract(
        {
            "collection_id": str,
            "document_id": str,
            "shard_id": str,
            "attempt_id": str,
            "attempt_number": int,
            "attempt_kind": str,
            "pool_key": str,
            "model_id": str,
            "attempt_state": str,
        },
        {"worker_id": _NULLABLE_STRING},
    ),
    "attempt.output.received.v1": _contract(
        {
            "collection_id": str,
            "document_id": str,
            "shard_id": str,
            "attempt_id": str,
            "output_sha256": str,
            "gpu_milliseconds": int,
            "attempt_state": str,
        }
    ),
    "attempt.validation.failed.v1": _contract(
        {
            "collection_id": str,
            "document_id": str,
            "shard_id": str,
            "attempt_id": str,
            "validation_id": str,
            "validation_level": int,
            "validator_key": str,
            "reason_codes": list,
            "hard_fail": bool,
            "attempt_state": str,
        }
    ),
    "attempt.accepted.v1": _contract(
        {
            "collection_id": str,
            "document_id": str,
            "shard_id": str,
            "attempt_id": str,
            "final_state": str,
            "authority_tier": str,
            "billable": bool,
            "cost_usd": str,
        }
    ),
    "attempt.rejected.v1": _contract(
        {
            "collection_id": str,
            "document_id": str,
            "shard_id": str,
            "attempt_id": str,
            "failure_domain": str,
            "reason_codes": list,
            "attempt_state": str,
        }
    ),
    "attempt.hedged.v1": _contract(
        {
            "collection_id": str,
            "document_id": str,
            "shard_id": str,
            "source_attempt_id": str,
            "hedge_attempt_id": str,
            "predicted_p95_milliseconds": int,
            "elapsed_milliseconds": int,
            "billing_disposition": str,
        }
    ),
    "worker.semantic.degraded.v1": _contract(
        {
            "collection_id": str,
            "worker_health_id": str,
            "worker_id": str,
            "pool_key": str,
            "semantic_score": str,
            "worker_state": str,
            "reason_codes": list,
        }
    ),
    "worker.draining.v1": _contract(
        {
            "collection_id": str,
            "worker_health_id": str,
            "worker_id": str,
            "pool_key": str,
            "worker_state": str,
            "reason_codes": list,
        }
    ),
    "worker.quarantined.v1": _contract(
        {
            "collection_id": str,
            "worker_health_id": str,
            "worker_id": str,
            "pool_key": str,
            "worker_state": str,
            "impacted_attempt_count": int,
            "reason_codes": list,
        }
    ),
    "recovery.region.requested.v1": _contract(
        {
            "collection_id": str,
            "document_id": str,
            "shard_id": str,
            "source_attempt_id": str,
            "recovery_task_id": str,
            "recovery_level": str,
            "reason_codes": list,
            "recovery_state": str,
        }
    ),
    "recovery.completed.v1": _contract(
        {
            "collection_id": str,
            "document_id": str,
            "shard_id": str,
            "recovery_task_id": str,
            "result_attempt_id": str,
            "recovery_level": str,
            "final_state": str,
        }
    ),
    "continuity.merge.started.v1": _contract(
        {
            "collection_id": str,
            "document_id": str,
            "merge_revision": str,
            "candidate_edge_count": int,
            "accepted_block_count": int,
        }
    ),
    "continuity.merge.completed.v1": _contract(
        {
            "collection_id": str,
            "document_id": str,
            "merge_revision": str,
            "accepted_edge_count": int,
            "deduplicated_block_count": int,
            "source_coverage_count": int,
            "unresolved_count": int,
            "continuity_sha256": str,
        }
    ),
    "document.finalized.v1": _contract(
        {
            "collection_id": str,
            "document_id": str,
            "final_state": str,
            "verified_block_count": int,
            "unresolved_count": int,
            "quarantined_count": int,
            "manifest_sha256": str,
            "billable_credits": str,
        }
    ),
}

if set(COLLECTION_EVENT_PAYLOAD_CONTRACTS) != set(COLLECTION_EVENT_TYPES):
    raise RuntimeError("collection event payload contracts must exactly cover the canonical enum")

COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS: dict[str, dict[str, PayloadFieldType]] = {
    event_type: dict(contract.required)
    for event_type, contract in COLLECTION_EVENT_PAYLOAD_CONTRACTS.items()
}
COLLECTION_EVENT_OPTIONAL_PAYLOAD_FIELDS: dict[str, dict[str, PayloadFieldType]] = {
    event_type: dict(contract.optional)
    for event_type, contract in COLLECTION_EVENT_PAYLOAD_CONTRACTS.items()
}

_UUID_FIELDS = frozenset(
    {
        "collection_id",
        "project_id",
        "source_root_id",
        "upload_session_id",
        "preflight_id",
        "estimate_run_id",
        "processing_job_id",
        "architecture_plan_id",
        "analysis_task_id",
        "billing_owner_job_id",
        "repair_id",
        "target_id",
        "decision_id",
        "execution_id",
        "registry_model_id",
        "export_id",
        "package_manifest_id",
        "package_validation_id",
        "document_id",
        "shard_id",
        "attempt_id",
        "validation_id",
        "source_attempt_id",
        "hedge_attempt_id",
        "worker_health_id",
        "recovery_task_id",
        "result_attempt_id",
    }
)
_DECIMAL_FIELDS = frozenset(
    {
        "credits",
        "hard_cap",
        "credit_p50",
        "credit_p95",
        "reserve_ceiling",
        "confidence",
        "credits_consumed",
        "cost_usd",
        "semantic_score",
        "billable_credits",
    }
)
_COUNT_MAP_FIELDS = frozenset(
    {
        "antivirus_status_counts",
        "asset_type_counts",
        "block_type_counts",
        "cdr_status_counts",
        "isolation_status_counts",
        "region_type_counts",
        "route_counts",
        "source_event_type_counts",
    }
)
_IDENTIFIER_LIST_FIELDS = frozenset({"reason_codes", "route_policy_versions"})
_INTEGER_LIST_FIELDS = frozenset({"sample_tiers"})
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL = re.compile(r"^(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,6})?$")
_FORBIDDEN_COLLECTION_KEYS = frozenset(
    {
        "body",
        "content",
        "document",
        "document_text",
        "email",
        "filename",
        "name",
        "path",
        "presigned_url",
        "prompt",
        "raw_output",
        "raw_text",
        "source_text",
        "token",
        "url",
    }
)
_COLLECTION_STATES = frozenset(
    {
        "CREATED",
        "DISCOVERING",
        "HASHING",
        "UPLOADING",
        "VERIFYING",
        "SECURITY_SCAN",
        "DEDUPLICATING",
        "INGESTED",
        "PREFLIGHTING",
        "ESTIMATED",
        "AWAITING_APPROVAL",
        "PROCESSING",
        "VERIFYING_OUTPUT",
        "KNOWLEDGE_COMPILING",
        "PACKAGING",
        "COMPLETED",
        "PAUSED",
        "PARTIAL",
        "FAILED_RETRYABLE",
        "UNRESOLVED",
        "QUARANTINED",
        "CANCEL_REQUESTED",
        "CANCELED",
        "PURGED",
    }
)
_SIGNATURE_STATES = frozenset(
    {"unsigned_external_key_required", "external_signer_required", "verified"}
)
COLLECTION_EVENT_ENUM_FIELDS: dict[str, dict[str, frozenset[str]]] = {
    "collection.source.created.v1": {
        "source_type": frozenset({"local", "google_drive", "onedrive"}),
    },
    "file.hash.progress.v1": {"hash_algorithm": frozenset({"sha256"})},
    "collection.paused.v1": {
        "paused_from": frozenset({"UPLOADING", "PROCESSING"}),
        "status": frozenset({"PAUSED"}),
    },
    "collection.resumed.v1": {
        "resumed_to": frozenset({"UPLOADING", "PROCESSING"}),
        "status": frozenset({"UPLOADING", "PROCESSING"}),
    },
    "estimate.fast.ready.v1": {
        "basis": frozenset({"repository_rule_v1", "adaptive_sample_rules_quantile_v1"})
    },
    "estimate.final.ready.v1": {
        "basis": frozenset({"repository_rule_v1", "adaptive_sample_rules_quantile_v1"}),
        "estimate_status": frozenset({"fast_ready", "sampled_ready", "incomplete"}),
    },
    "collection.preflight.completed.v1": {
        "estimate_status": frozenset({"fast_ready", "sampled_ready", "incomplete"})
    },
    "processing.started.v1": {
        "execution_scope": frozenset(
            {"existing_verified_artifacts_only", "collection_processing_runtime"}
        )
    },
    "region.detected.v1": {"evidence": frozenset({"persisted_block_projection"})},
    "table.reconstructed.v1": {"source": frozenset({"persisted_verified_blocks"})},
    "verification.failed.v1": {
        "state": frozenset(
            {
                "verified",
                "authority_verified",
                "auto_repaired",
                "verified_with_warning",
                "unresolved",
                "quarantined",
                "rejected",
            }
        )
    },
    "output.quarantined.v1": {"billing": frozenset({"unbillable"})},
    "integrity.decision.recorded.v1": {
        "target_type": frozenset({"quarantine_item", "review_item"}),
        "action": frozenset(
            {
                "keep_quarantined",
                "exclude",
                "retry_new_engine",
                "provide_password",
                "correct_source",
                "override",
            }
        ),
        "reason_code": frozenset(
            {
                "ACCEPTED_QUARANTINE",
                "EXCLUDED_FROM_OUTPUT",
                "RETRY_WITH_APPROVED_ENGINE",
                "ENCRYPTED_PDF_SECRET_SUBMITTED",
                "CORRECTED_SOURCE_SUBMITTED",
                "CUSTOMER_OVERRIDE_APPROVED",
            }
        ),
        "result_status": frozenset({"resolved", "rejected", "retrying"}),
        "evidence_reference_kind": frozenset(
            {
                "none",
                "artifact_sha256",
                "analysis_task",
                "source_file",
                "engine_revision",
                "support_case",
            }
        ),
    },
    "integrity.action.state_changed.v1": {
        "target_type": frozenset({"quarantine_item", "review_item"}),
        "action": frozenset(
            {
                "keep_quarantined",
                "exclude",
                "retry_new_engine",
                "provide_password",
                "correct_source",
                "override",
            }
        ),
        "status": frozenset({"queued", "running", "completed", "failed"}),
    },
    "entity.resolved.v1": {"scope": frozenset({"collection_evidence_blocks"})},
    "export.started.v1": {
        "profile": frozenset({"collection_manifest_v1", "complete_knowledge_v1"}),
        "completion_scope": frozenset(
            {"repository_manifest_only", "complete_knowledge_package"}
        ),
    },
    "export.ready.v1": {"signature_status": _SIGNATURE_STATES},
    "package.validated.v1": {"validation_status": frozenset({"passed", "failed"})},
    "package.signed.v1": {"signature_status": _SIGNATURE_STATES},
    "collection.export.completed.v1": {
        "profile": frozenset({"collection_manifest_v1", "complete_knowledge_v1"}),
        "signature_status": _SIGNATURE_STATES,
        "completion_scope": frozenset(
            {"repository_manifest_only", "complete_knowledge_package"}
        ),
    },
    "collection.completed.v1": {
        "profile": frozenset({"collection_manifest_v1", "complete_knowledge_v1"}),
        "signature_status": _SIGNATURE_STATES,
        "status": frozenset({"COMPLETED"}),
    },
    "collection.deletion.requested.v1": {
        "status": frozenset({"CANCEL_REQUESTED"})
    },
    "collection.purged.v1": {"status": frozenset({"PURGED"})},
    "shard.planned.v1": {"shard_state": frozenset({"PLANNED"})},
    "shard.dispatched.v1": {
        "shard_state": frozenset({"DISPATCHED", "RUNNING"})
    },
    "attempt.started.v1": {
        "attempt_state": frozenset({"QUEUED", "RUNNING"}),
        "attempt_kind": frozenset(
            {"primary", "retry", "hedge", "straggler", "recovery", "shadow"}
        ),
    },
    "attempt.output.received.v1": {
        "attempt_state": frozenset({"OUTPUT_RECEIVED", "VALIDATING"})
    },
    "attempt.validation.failed.v1": {
        "attempt_state": frozenset(
            {"VALIDATING", "REJECTED", "RETRYABLE_FAILED", "QUARANTINED"}
        )
    },
    "attempt.accepted.v1": {
        "final_state": frozenset(
            {
                "verified",
                "authority_verified",
                "cross_model_verified",
                "auto_repaired",
            }
        ),
        "authority_tier": frozenset(
            {"exact_authority", "native", "pixel_ocr", "independent_agreement"}
        ),
    },
    "attempt.rejected.v1": {
        "failure_domain": frozenset(
            {"infrastructure", "semantic", "policy", "cancelled"}
        ),
        "attempt_state": frozenset(
            {"REJECTED", "RETRYABLE_FAILED", "TERMINAL_FAILED", "QUARANTINED"}
        ),
    },
    "attempt.hedged.v1": {
        "billing_disposition": frozenset({"speculative_unbillable"})
    },
    "worker.semantic.degraded.v1": {
        "worker_state": frozenset({"DEGRADED", "DRAINING", "QUARANTINED"})
    },
    "worker.draining.v1": {"worker_state": frozenset({"DRAINING"})},
    "worker.quarantined.v1": {"worker_state": frozenset({"QUARANTINED"})},
    "recovery.region.requested.v1": {
        "recovery_level": frozenset({"cell", "row", "table", "region", "page", "page_group"}),
        "recovery_state": frozenset({"REQUESTED", "QUEUED"}),
    },
    "recovery.completed.v1": {
        "recovery_level": frozenset({"cell", "row", "table", "region", "page", "page_group"}),
        "final_state": frozenset(
            {
                "verified",
                "authority_verified",
                "cross_model_verified",
                "auto_repaired",
                "unresolved",
                "quarantined",
                "failed",
            }
        ),
    },
    "document.finalized.v1": {
        "final_state": frozenset(
            {
                "verified",
                "authority_verified",
                "cross_model_verified",
                "auto_repaired",
                "unresolved",
                "quarantined",
                "failed",
            }
        )
    },
}


def _enum_values(event_type: str, key: str) -> frozenset[str] | None:
    explicit = COLLECTION_EVENT_ENUM_FIELDS.get(event_type, {}).get(key)
    if explicit is not None:
        return explicit
    return _COLLECTION_STATES if key == "status" else None


def _validate_collection_payload_shape(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        if len(value) > 256:
            raise ValueError(f"collection event mapping is too large at {path}")
        for key, item in value.items():
            normalized = str(key).casefold()
            if (
                normalized in _FORBIDDEN_COLLECTION_KEYS
                or normalized.endswith(("_path", "_url"))
            ):
                raise ValueError(f"PII or raw collection event field is forbidden at {path}")
            _validate_collection_payload_shape(item, path=f"{path}.{normalized}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _validate_collection_payload_shape(item, path=f"{path}[{index}]")


def _validate_payload_field(event_type: str, key: str, value: object) -> None:
    if value is None:
        return
    if key in _UUID_FIELDS:
        try:
            parsed = uuid.UUID(str(value))
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"collection event field {key} must be a UUID") from exc
        if str(parsed) != value:
            raise ValueError(f"collection event field {key} must be a canonical UUID")
    if key.endswith("_sha256") and (not isinstance(value, str) or not _SHA256.fullmatch(value)):
        raise ValueError(f"collection event field {key} must be a lowercase SHA-256")
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and (value < 0 or value > 9_223_372_036_854_775_807)
    ):
        raise ValueError(f"collection event field {key} is outside the integer bound")
    if key in _DECIMAL_FIELDS and isinstance(value, str):
        if not _DECIMAL.fullmatch(value):
            raise ValueError(f"collection event field {key} must be a bounded decimal string")
        try:
            parsed_decimal = Decimal(value)
        except InvalidOperation as exc:  # pragma: no cover - regex is the primary gate
            raise ValueError(f"collection event field {key} is not decimal") from exc
        if not parsed_decimal.is_finite() or parsed_decimal < 0:
            raise ValueError(f"collection event field {key} must be finite and nonnegative")
        if key == "confidence" and parsed_decimal > 1:
            raise ValueError("collection event confidence must be between zero and one")
    if key in _COUNT_MAP_FIELDS:
        assert isinstance(value, dict)
        if len(value) > 128 or any(
            not isinstance(map_key, str)
            or not _IDENTIFIER.fullmatch(map_key)
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count < 0
            for map_key, count in value.items()
        ):
            raise ValueError(f"collection event field {key} must be a bounded count map")
    if key in _IDENTIFIER_LIST_FIELDS:
        assert isinstance(value, list)
        if len(value) > 128 or any(
            not isinstance(item, str) or not _IDENTIFIER.fullmatch(item) for item in value
        ):
            raise ValueError(f"collection event field {key} must be bounded identifiers")
    if key in _INTEGER_LIST_FIELDS:
        assert isinstance(value, list)
        if len(value) > 128 or any(
            not isinstance(item, int) or isinstance(item, bool) or item < 0 for item in value
        ):
            raise ValueError(f"collection event field {key} must be bounded integers")
    enum_values = _enum_values(event_type, key)
    if enum_values is not None and value not in enum_values:
        raise ValueError(f"collection event field {key} is outside its enum")
    if (
        isinstance(value, str)
        and key not in _UUID_FIELDS
        and not key.endswith("_sha256")
        and key not in _DECIMAL_FIELDS
        and (len(value) > 160 or not _IDENTIFIER.fullmatch(value))
    ):
        raise ValueError(f"collection event field {key} must be a bounded identifier")


def collection_event_payload_field_schema(
    event_type: str,
    key: str,
    expected: PayloadFieldType,
) -> dict[str, object]:
    expected_types = expected if isinstance(expected, tuple) else (expected,)
    json_types = []
    for item in expected_types:
        json_types.append(
            "string"
            if item is str
            else "integer"
            if item is int
            else "boolean"
            if item is bool
            else "object"
            if item is dict
            else "array"
            if item is list
            else "null"
        )
    schema: dict[str, object] = {
        "type": json_types[0] if len(json_types) == 1 else json_types,
    }
    if key in _UUID_FIELDS:
        schema.update({"format": "uuid", "pattern": r"^[0-9a-f-]{36}$"})
    elif key.endswith("_sha256"):
        schema.update({"pattern": _SHA256.pattern, "minLength": 64, "maxLength": 64})
    elif key in _DECIMAL_FIELDS and str in expected_types:
        schema.update({"pattern": _DECIMAL.pattern, "maxLength": 25})
    elif str in expected_types:
        schema.update({"pattern": _IDENTIFIER.pattern, "maxLength": 160})
    if int in expected_types:
        schema.update({"minimum": 0, "maximum": 9_223_372_036_854_775_807})
    if key in _COUNT_MAP_FIELDS:
        schema.update(
            {
                "maxProperties": 128,
                "propertyNames": {"pattern": _IDENTIFIER.pattern},
                "additionalProperties": {"type": "integer", "minimum": 0},
            }
        )
    if key in _IDENTIFIER_LIST_FIELDS:
        schema.update(
            {
                "maxItems": 128,
                "items": {"type": "string", "pattern": _IDENTIFIER.pattern},
            }
        )
    if key in _INTEGER_LIST_FIELDS:
        schema.update(
            {
                "maxItems": 128,
                "items": {"type": "integer", "minimum": 0},
            }
        )
    enum_values = _enum_values(event_type, key)
    if enum_values is not None:
        schema["enum"] = sorted(enum_values)
    return schema


def validate_collection_event_payload(
    event_type: CollectionEventType | str,
    payload: Mapping[str, Any],
    *,
    collection_id: uuid.UUID,
    job_id: uuid.UUID | None,
) -> dict[str, Any]:
    canonical_type = str(CollectionEventType(event_type))
    contract = COLLECTION_EVENT_PAYLOAD_CONTRACTS[canonical_type]
    safe = cast(dict[str, Any], validate_public_payload(dict(payload)))
    _validate_collection_payload_shape(safe)
    if len(json.dumps(safe, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 64 * 1024:
        raise ValueError("collection event payload exceeds 64 KiB")
    missing = contract.required.keys() - safe.keys()
    if missing:
        raise ValueError(f"collection event payload is missing required keys: {sorted(missing)}")
    known = {**contract.required, **contract.optional}
    invalid = [
        key
        for key, expected in known.items()
        if key in safe and not _matches_payload_type(safe[key], expected)
    ]
    if invalid:
        raise ValueError(f"collection event payload has invalid field types: {sorted(invalid)}")
    for key in known.keys() & safe.keys():
        _validate_payload_field(canonical_type, key, safe[key])
    if safe["collection_id"] != str(collection_id):
        raise ValueError("collection event payload identity mismatch")
    payload_job_id = safe.get("processing_job_id")
    if payload_job_id is not None and (job_id is None or payload_job_id != str(job_id)):
        raise ValueError("collection event processing job correlation mismatch")
    return safe


class CollectionEventEnvelope(ContractModel):
    """Strict, versioned collection SSE and replay envelope."""

    model_config = ConfigDict(
        alias_generator=None,
        serialize_by_alias=False,
        extra="forbid",
    )

    event_id: uuid.UUID
    collection_id: uuid.UUID
    job_id: uuid.UUID | None
    sequence: Annotated[int, Field(ge=1)]
    event_type: CollectionEventType
    timestamp: datetime
    payload: dict[str, Any]
    schema_version: Literal["1.0"]

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @field_validator("payload")
    @classmethod
    def reject_private_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], validate_public_payload(value))

    @model_validator(mode="after")
    def validate_typed_payload(self) -> CollectionEventEnvelope:
        safe = validate_collection_event_payload(
            self.event_type,
            self.payload,
            collection_id=self.collection_id,
            job_id=self.job_id,
        )
        object.__setattr__(self, "payload", safe)
        return self


def _matches_payload_type(value: object, expected: PayloadFieldType) -> bool:
    expected_types = expected if isinstance(expected, tuple) else (expected,)
    if int in expected_types and isinstance(value, bool):
        return False
    return isinstance(value, expected_types)
