"""Strict semantic merge and ACL admission tests for the A-D pipeline."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from akc_api.knowledge_gpu import (
    StageCInput,
    StageDInput,
    canonical_json_bytes,
    validate_knowledge_stage_result,
)
from pydantic import ValidationError

PROMPT_REVISION = "sha256:" + ("1" * 64)
SCHEMA_REVISION = "sha256:" + ("2" * 64)


def _candidate(
    candidate_id: str,
    block_id: str,
    *,
    title: str,
    summary: str,
    tags: list[str],
) -> dict[str, Any]:
    snippet = f"Evidence for {candidate_id}"
    return {
        "candidate_id": candidate_id,
        "normalized_title": title,
        "note_type": "concept",
        "summary": summary,
        "aliases": [],
        "tags": tags,
        "claims": [],
        "evidence_block_ids": [block_id],
        "evidence": [
            {
                "block_id": block_id,
                "snippet": snippet,
                "snippet_sha256": hashlib.sha256(snippet.encode()).hexdigest(),
            }
        ],
    }


def _stage_c_input(*, equivalent: bool) -> StageCInput:
    return StageCInput.model_validate(
        {
            "unit_id": "stage.c.unit",
            "document_id": "document.one",
            "document_version_id": "document.one:v1",
            "candidates": [
                _candidate(
                    "candidate.one",
                    "block.one",
                    title="Access control",
                    summary="Project authorization rules",
                    tags=["security"],
                ),
                _candidate(
                    "candidate.two",
                    "block.two",
                    title="Access control" if equivalent else "Invoice total",
                    summary=(
                        "Project authorization rules" if equivalent else "Quarterly currency amount"
                    ),
                    tags=["security"] if equivalent else ["finance"],
                ),
            ],
        }
    )


def _admit_stage_c(
    stage_input: StageCInput,
    groups: list[dict[str, Any]],
) -> None:
    validate_knowledge_stage_result(
        output_payload={
            "knowledge_stage_result": {
                "schemaVersion": "knowledge-pipeline-result-1.0.0",
                "stage": "C",
                "unitId": stage_input.unit_id,
                "mergeGroups": groups,
            },
            "provider_metrics": {
                "prompt_sha256": PROMPT_REVISION,
                "knowledge_schema_sha256": SCHEMA_REVISION,
                "knowledge_stage": "C",
                "knowledge_unit_id": stage_input.unit_id,
                "unsupported_claim_count": 0,
            },
        },
        input_body=canonical_json_bytes(stage_input),
        expected_prompt_revision=PROMPT_REVISION,
        expected_schema_sha256=SCHEMA_REVISION,
        expected_stage="C",
        expected_unit_id=stage_input.unit_id,
    )


def test_semantically_equivalent_candidates_can_merge_with_exact_evidence() -> None:
    stage_input = _stage_c_input(equivalent=True)
    _admit_stage_c(
        stage_input,
        [
            {
                "groupId": "group.access-control",
                "canonicalCandidateId": "candidate.one",
                "memberCandidateIds": ["candidate.one", "candidate.two"],
                "comparedCandidateIds": ["candidate.one", "candidate.two"],
                "evidenceBlockIds": ["block.one", "block.two"],
                "reason": (
                    "Both candidates have the exact normalized title and security "
                    "tag, with each source block retained."
                ),
            }
        ],
    )


def test_semantically_distinct_candidates_must_remain_separate() -> None:
    stage_input = _stage_c_input(equivalent=False)
    separate = [
        {
            "groupId": f"group.{index}",
            "canonicalCandidateId": candidate.candidate_id,
            "memberCandidateIds": [candidate.candidate_id],
            "comparedCandidateIds": [candidate.candidate_id],
            "evidenceBlockIds": list(candidate.evidence_block_ids),
            "reason": "No equivalent semantic descriptor was supplied.",
        }
        for index, candidate in enumerate(stage_input.candidates)
    ]
    _admit_stage_c(stage_input, separate)

    with pytest.raises(
        ValueError,
        match="knowledge_stage_c_merge_semantics_unsupported",
    ):
        _admit_stage_c(
            stage_input,
            [
                {
                    "groupId": "group.unsupported",
                    "canonicalCandidateId": "candidate.one",
                    "memberCandidateIds": ["candidate.one", "candidate.two"],
                    "comparedCandidateIds": ["candidate.one", "candidate.two"],
                    "evidenceBlockIds": ["block.one", "block.two"],
                    "reason": "The model guessed these concepts were related.",
                }
            ],
        )


def test_merge_group_cannot_hide_an_unrelated_orphan_candidate() -> None:
    equivalent = _stage_c_input(equivalent=True)
    value = equivalent.model_dump(mode="json")
    value["candidates"].append(
        _candidate(
            "candidate.three",
            "block.three",
            title="Invoice total",
            summary="Quarterly currency amount",
            tags=["finance"],
        )
    )
    stage_input = StageCInput.model_validate(value)

    with pytest.raises(
        ValueError,
        match="knowledge_stage_c_merge_semantics_unsupported",
    ):
        _admit_stage_c(
            stage_input,
            [
                {
                    "groupId": "group.partially-supported",
                    "canonicalCandidateId": "candidate.one",
                    "memberCandidateIds": [
                        "candidate.one",
                        "candidate.two",
                        "candidate.three",
                    ],
                    "comparedCandidateIds": [
                        "candidate.one",
                        "candidate.two",
                        "candidate.three",
                    ],
                    "evidenceBlockIds": [
                        "block.one",
                        "block.two",
                        "block.three",
                    ],
                    "reason": (
                        "Two candidates match, but the third has no semantic supporting edge."
                    ),
                }
            ],
        )


def test_stage_d_requires_exact_acl_attestation_and_no_unverified_links() -> None:
    source = _candidate(
        "candidate.one",
        "block.one",
        title="Access control",
        summary="Project authorization rules",
        tags=["security"],
    )
    tenant_id = "tenant.one"
    project_id = "project.one"
    scope_hash = hashlib.sha256("\0".join((tenant_id, project_id)).encode()).hexdigest()
    stage_input = StageDInput.model_validate(
        {
            "unit_id": "stage.d.unit",
            "tenant_id": tenant_id,
            "document_id": "document.one",
            "document_version_id": "document.one:v1",
            "allowed_project_ids": [project_id],
            "acl_attestation": {
                "tenant_id": tenant_id,
                "allowed_project_ids": [project_id],
                "scope_sha256": scope_hash,
            },
            "source_candidates": [source],
            "retrieval_status": "provider_unverified",
            "retrieval_candidates": [],
        }
    )
    result = validate_knowledge_stage_result(
        output_payload={
            "knowledge_stage_result": {
                "schemaVersion": "knowledge-pipeline-result-1.0.0",
                "stage": "D",
                "unitId": stage_input.unit_id,
                "retrievalStatus": "provider_unverified",
                "links": [],
            },
            "provider_metrics": {
                "prompt_sha256": PROMPT_REVISION,
                "knowledge_schema_sha256": SCHEMA_REVISION,
                "knowledge_stage": "D",
                "knowledge_unit_id": stage_input.unit_id,
                "unsupported_claim_count": 0,
            },
        },
        input_body=canonical_json_bytes(stage_input),
        expected_prompt_revision=PROMPT_REVISION,
        expected_schema_sha256=SCHEMA_REVISION,
        expected_stage="D",
        expected_unit_id=stage_input.unit_id,
    )
    assert result.links == ()

    invalid = stage_input.model_dump(mode="json")
    invalid["acl_attestation"]["scope_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="ACL attestation scope mismatch"):
        StageDInput.model_validate(invalid)
