from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import unittest
from unittest import mock

from runtime import (
    HandlerRuntime,
    WorkerConfig,
    _validate_adapter_output,
    _validate_tenant_object_key,
    _validate_url,
    build_handler,
)

REVISION = "1" * 40
IMAGE_DIGEST = "sha256:" + ("2" * 64)
ADAPTER_VERSION = "test-adapter-1.0.0"


class WorkerRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.update(
            {
                "MODEL_REVISION": REVISION,
                "RUNTIME_IMAGE_DIGEST": IMAGE_DIGEST,
                "ADAPTER_VERSION": ADAPTER_VERSION,
                "AKC_ADAPTER_MODE": "mock",
                "ALLOW_INLINE_INPUT": "true",
                "GPU_USD_PER_SECOND": "0.00019",
                "REQUIRE_CALLBACK_AUTH": "false",
                "CALLBACK_HMAC_SECRET": "",
                "MAX_INPUT_BYTES": str(25 * 1024 * 1024),
                "MAX_OUTPUT_BYTES": str(10 * 1024 * 1024),
                "MAX_DIRECT_RESPONSE_BYTES": str(1024 * 1024),
                "INPUT_HOST_ALLOWLIST": "",
                "OUTPUT_HOST_ALLOWLIST": "",
            }
        )

    def event(self, key: str = "key-1", text: str = "hello") -> dict:
        return {
            "input": {
                "job_id": "job-1",
                "tenant_id": "tenant-1",
                "idempotency_key": key,
                "expected_model_revision": REVISION,
                "expected_runtime_image_digest": IMAGE_DIGEST,
                "expected_adapter_version": ADAPTER_VERSION,
                "inline_bytes_b64": base64.b64encode(b"fixture").decode(),
                "document_id": "urn:akmp:doc:test",
                "document_version_id": "urn:akmp:doc-version:test-v1",
                "page_index": 0,
                "options": {"mock_text": text, "bbox1000": [10, 20, 900, 800]},
            }
        }

    def test_exact_revision_is_required(self) -> None:
        os.environ["MODEL_REVISION"] = "latest"
        with self.assertRaisesRegex(RuntimeError, "exact_model_revision_required"):
            build_handler("parser", "test")

    def test_control_plane_attestation_is_mandatory_and_exact(self) -> None:
        handler = build_handler("parser", "test")
        missing = self.event()
        missing["input"].pop("expected_runtime_image_digest")
        self.assertEqual(
            handler(missing)["error"]["code"],
            "worker_attestation_mismatch",
        )
        mismatched = self.event()
        mismatched["input"]["expected_adapter_version"] = "wrong-adapter-1.0.0"
        self.assertEqual(
            handler(mismatched)["error"]["code"],
            "worker_attestation_mismatch",
        )

    def test_production_rejects_local_mock_revision(self) -> None:
        os.environ["AKC_ADAPTER_MODE"] = "production"
        with self.assertRaisesRegex(RuntimeError, "production_model_revision_required"):
            build_handler("parser", "test")

    def test_parser_result_has_revision_evidence_and_cost(self) -> None:
        result = build_handler("parser", "test")(self.event())
        self.assertTrue(result["ok"])
        self.assertEqual(result["model_revision"], REVISION)
        self.assertEqual(result["blocks"][0]["source_refs"][0]["bbox1000"], [10, 20, 900, 800])
        self.assertIn("estimated_cost_usd", result["metrics"])

    def test_repeated_key_returns_same_result(self) -> None:
        handler = build_handler("parser", "test")
        first = handler(self.event())
        second = handler(self.event())
        self.assertEqual(first["result_id"], second["result_id"])
        self.assertTrue(second["idempotent_replay"])

    def test_reused_key_with_different_request_conflicts(self) -> None:
        handler = build_handler("parser", "test")
        handler(self.event(text="one"))
        result = handler(self.event(text="two"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "idempotency_conflict")

    def test_experimental_worker_is_disabled_by_default(self) -> None:
        os.environ["EXPERIMENT_ENABLED"] = "false"
        result = build_handler("parser", "hpd", experimental=True)(self.event())
        self.assertEqual(result["error"]["code"], "experimental_worker_disabled")

    def test_knowledge_mock_requires_evidence_blocks(self) -> None:
        event = self.event()
        event["input"]["inline_bytes_b64"] = base64.b64encode(
            json.dumps(
                {
                    "schema_version": "knowledge-input-1.0.0",
                    "document_id": "urn:akmp:doc:test",
                    "document_version_id": "urn:akmp:doc-version:test-v1",
                    "title": "No blocks",
                    "blocks": [],
                }
            ).encode()
        ).decode()
        result = build_handler("knowledge", "test")(event)
        self.assertEqual(result["error"]["code"], "knowledge_blocks_required")

    def test_knowledge_adapter_cannot_cite_unsupplied_evidence(self) -> None:
        request = {
            "options": {
                "artifact_contract": "akc-knowledge-bundle-1.0.0",
                "prompt_revision": "sha256:" + ("3" * 64),
                "knowledge_schema_sha256": "sha256:" + ("4" * 64),
            },
            "knowledge_input": {
                "schema_version": "knowledge-input-1.0.0",
                "document_id": "urn:akmp:doc:test",
                "document_version_id": "urn:akmp:doc-version:test-v1",
                "title": "Source",
                "blocks": [
                    {
                        "block_id": "blk_supplied",
                        "text": "source",
                        "source_refs": [{"page_index": 0}],
                    }
                ]
            },
        }
        with self.assertRaisesRegex(RuntimeError, "knowledge_evidence_required"):
            _validate_adapter_output(
                {
                    "knowledge_bundle": {
                        "schemaVersion": "knowledge-1.0.0",
                        "documentId": "urn:akmp:doc:test",
                        "notes": [
                            {
                                "noteId": "note.one",
                                "title": "Unsupported",
                                "noteType": "document",
                                "contentOrigin": "ai_inferred",
                                "evidenceBlockIds": ["blk_hallucinated"],
                                "summary": "unsupported",
                                "claims": [],
                                "aliases": [],
                                "tags": [],
                                "relatedNoteCandidates": [],
                                "reviewStatus": "pending",
                            }
                        ],
                        "relations": [],
                        "conflicts": [],
                    },
                    "warnings": [],
                    "provider_metrics": {
                        "prompt_sha256": "sha256:" + ("3" * 64),
                        "knowledge_schema_sha256": "sha256:" + ("4" * 64),
                        "unsupported_claim_count": 0,
                    },
                },
                worker_kind="knowledge",
                request=request,
            )

    def test_staged_knowledge_mock_validates_bounded_semantic_descriptors(self) -> None:
        snippet = "Evidence for the access control candidate."
        candidate = {
            "candidate_id": "candidate.access-control",
            "normalized_title": "Access control",
            "note_type": "concept",
            "summary": "Project authorization rules",
            "aliases": [],
            "tags": ["security"],
            "claims": [],
            "evidence_block_ids": ["block.access-control"],
            "evidence": [
                {
                    "block_id": "block.access-control",
                    "snippet": snippet,
                    "snippet_sha256": hashlib.sha256(snippet.encode()).hexdigest(),
                }
            ],
        }
        knowledge_input = {
            "schema_version": "knowledge-pipeline-input-1.0.0",
            "stage": "C",
            "unit_id": "stage.c.unit",
            "document_id": "urn:akmp:doc:test",
            "document_version_id": "urn:akmp:doc-version:test-v1",
            "candidates": [candidate],
        }
        event = self.event(key="knowledge-stage-c")
        event["input"]["inline_bytes_b64"] = base64.b64encode(
            json.dumps(knowledge_input).encode()
        ).decode()
        event["input"]["options"] = {
            "artifact_contract": "akc-knowledge-pipeline-stage-1.0.0",
            "prompt_revision": "sha256:" + ("3" * 64),
            "knowledge_schema_sha256": "sha256:" + ("4" * 64),
            "knowledge_stage": "C",
            "knowledge_unit_id": "stage.c.unit",
        }

        result = build_handler("knowledge", "test")(event)

        self.assertTrue(result["ok"])
        self.assertEqual(result["knowledge_stage_result"]["stage"], "C")
        self.assertEqual(
            result["provider_metrics"]["knowledge_unit_id"],
            "stage.c.unit",
        )

    def test_staged_knowledge_rejects_forged_acl_attestation(self) -> None:
        snippet = "Evidence for the source candidate."
        source = {
            "candidate_id": "candidate.source",
            "normalized_title": "Source",
            "note_type": "concept",
            "summary": "Source summary",
            "aliases": [],
            "tags": [],
            "claims": [],
            "evidence_block_ids": ["block.source"],
            "evidence": [
                {
                    "block_id": "block.source",
                    "snippet": snippet,
                    "snippet_sha256": hashlib.sha256(snippet.encode()).hexdigest(),
                }
            ],
        }
        knowledge_input = {
            "schema_version": "knowledge-pipeline-input-1.0.0",
            "stage": "D",
            "unit_id": "stage.d.unit",
            "tenant_id": "tenant-1",
            "document_id": "urn:akmp:doc:test",
            "document_version_id": "urn:akmp:doc-version:test-v1",
            "allowed_project_ids": ["project-1"],
            "acl_attestation": {
                "tenant_id": "tenant-1",
                "allowed_project_ids": ["project-1"],
                "scope_sha256": "0" * 64,
            },
            "source_candidates": [source],
            "retrieval_status": "provider_unverified",
            "retrieval_candidates": [],
        }
        event = self.event(key="knowledge-stage-d-forged-acl")
        event["input"]["inline_bytes_b64"] = base64.b64encode(
            json.dumps(knowledge_input).encode()
        ).decode()
        event["input"]["options"] = {
            "artifact_contract": "akc-knowledge-pipeline-stage-1.0.0",
            "prompt_revision": "sha256:" + ("3" * 64),
            "knowledge_schema_sha256": "sha256:" + ("4" * 64),
            "knowledge_stage": "D",
            "knowledge_unit_id": "stage.d.unit",
        }

        result = build_handler("knowledge", "test")(event)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "knowledge_stage_d_input_invalid")

    def test_staged_knowledge_rejects_unsupported_semantic_merge(self) -> None:
        def candidate(
            candidate_id: str,
            block_id: str,
            title: str,
            summary: str,
        ) -> dict:
            snippet = f"Evidence for {candidate_id}"
            return {
                "candidate_id": candidate_id,
                "normalized_title": title,
                "note_type": "concept",
                "summary": summary,
                "aliases": [],
                "tags": [],
                "claims": [],
                "evidence_block_ids": [block_id],
                "evidence": [
                    {
                        "block_id": block_id,
                        "snippet": snippet,
                        "snippet_sha256": hashlib.sha256(
                            snippet.encode()
                        ).hexdigest(),
                    }
                ],
            }

        request = {
            "options": {
                "artifact_contract": "akc-knowledge-pipeline-stage-1.0.0",
                "prompt_revision": "sha256:" + ("3" * 64),
                "knowledge_schema_sha256": "sha256:" + ("4" * 64),
                "knowledge_stage": "C",
                "knowledge_unit_id": "stage.c.unit",
            },
            "knowledge_input": {
                "schema_version": "knowledge-pipeline-input-1.0.0",
                "stage": "C",
                "unit_id": "stage.c.unit",
                "document_id": "urn:akmp:doc:test",
                "document_version_id": "urn:akmp:doc-version:test-v1",
                "candidates": [
                    candidate(
                        "candidate.access",
                        "block.access",
                        "Access control",
                        "Authorization rules",
                    ),
                    candidate(
                        "candidate.invoice",
                        "block.invoice",
                        "Invoice total",
                        "Currency amount",
                    ),
                ],
            },
        }
        output = {
            "knowledge_stage_result": {
                "schemaVersion": "knowledge-pipeline-result-1.0.0",
                "stage": "C",
                "unitId": "stage.c.unit",
                "mergeGroups": [
                    {
                        "groupId": "group.unsupported",
                        "canonicalCandidateId": "candidate.access",
                        "memberCandidateIds": [
                            "candidate.access",
                            "candidate.invoice",
                        ],
                        "comparedCandidateIds": [
                            "candidate.access",
                            "candidate.invoice",
                        ],
                        "evidenceBlockIds": ["block.access", "block.invoice"],
                        "reason": "The model guessed that they belong together.",
                    }
                ],
            },
            "provider_metrics": {
                "prompt_sha256": "sha256:" + ("3" * 64),
                "knowledge_schema_sha256": "sha256:" + ("4" * 64),
                "knowledge_stage": "C",
                "knowledge_unit_id": "stage.c.unit",
                "unsupported_claim_count": 0,
            },
        }

        with self.assertRaisesRegex(
            RuntimeError,
            "knowledge_stage_c_merge_semantics_unsupported",
        ):
            _validate_adapter_output(
                output,
                worker_kind="knowledge",
                request=request,
            )

    def test_non_https_input_is_rejected_before_network(self) -> None:
        event = self.event()
        event["input"].pop("inline_bytes_b64")
        event["input"]["input_url"] = "http://example.com/tenants/tenant-1/source/input.png"
        event["input"]["input_object_key"] = "tenants/tenant-1/source/input.png"
        result = build_handler("parser", "test")(event)
        self.assertEqual(result["error"]["code"], "https_required")

    def test_inline_input_is_disabled_unless_explicitly_enabled(self) -> None:
        os.environ["ALLOW_INLINE_INPUT"] = "false"
        result = build_handler("parser", "test")(self.event())
        self.assertEqual(result["error"]["code"], "inline_input_forbidden")

    def test_invalid_bbox1000_is_rejected(self) -> None:
        event = self.event()
        event["input"]["options"]["bbox1000"] = [10, 20, 10, 800]
        result = build_handler("parser", "test")(event)
        self.assertEqual(result["error"]["code"], "invalid_bbox1000")

    def test_callback_token_is_signature_audience_job_and_tenant_scoped(self) -> None:
        secret = "s" * 32
        os.environ["REQUIRE_CALLBACK_AUTH"] = "true"
        os.environ["CALLBACK_HMAC_SECRET"] = secret
        now = int(time.time())
        header = {"alg": "HS256", "typ": "JWT"}
        claims = {
            "aud": "akc-gpu-worker",
            "exp": now + 300,
            "iat": now,
            "job_id": "job-1",
            "scope": "gpu:execute",
            "tenant_id": "tenant-1",
        }

        def encode(value: dict) -> str:
            return (
                base64.urlsafe_b64encode(
                    json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
                )
                .decode()
                .rstrip("=")
            )

        signing_input = f"{encode(header)}.{encode(claims)}"
        signature = (
            base64.urlsafe_b64encode(
                hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
            )
            .decode()
            .rstrip("=")
        )
        event = self.event()
        event["input"]["callback_token"] = f"{signing_input}.{signature}"
        self.assertTrue(build_handler("parser", "test")(event)["ok"])
        event["input"]["tenant_id"] = "tenant-2"
        rejected = build_handler("parser", "test")(event)
        self.assertEqual(rejected["error"]["code"], "callback_token_scope_mismatch")

    def test_url_object_key_requires_exact_tenant_scope(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "tenant_scope_mismatch"):
            _validate_tenant_object_key(
                "tenants/tenant-2/source/input.bin",
                tenant_id="tenant-1",
                field="input_object_key",
            )
        event = self.event()
        event["input"].pop("inline_bytes_b64")
        event["input"]["input_url"] = "https://objects.example/tenants/tenant-2/input.bin"
        event["input"]["input_object_key"] = "tenants/tenant-2/input.bin"
        result = build_handler("parser", "test")(event)
        self.assertEqual(result["error"]["code"], "input_object_key_tenant_scope_mismatch")

    def test_dns_result_is_pinned_for_connection(self) -> None:
        os.environ["INPUT_HOST_ALLOWLIST"] = "objects.example"
        config = WorkerConfig.from_env("parser", "test")
        with mock.patch(
            "runtime.socket.getaddrinfo",
            return_value=[
                (
                    2,
                    1,
                    6,
                    "",
                    ("93.184.216.34", 443),
                )
            ],
        ):
            endpoint = _validate_url(
                "https://objects.example/tenants/tenant-1/input.bin",
                config.allowed_input_hosts,
                config,
            )
        self.assertEqual(endpoint.pinned_ip, "93.184.216.34")
        self.assertEqual(endpoint.host, "objects.example")

    def test_adapter_cannot_override_response_schema(self) -> None:
        runtime = HandlerRuntime(WorkerConfig.from_env("parser", "test"))

        class MaliciousAdapter:
            def self_test(self) -> None:
                return None

            def process(self, input_path, request):
                return {"ok": True, "tenant_id": "tenant-2", "blocks": []}

        runtime.adapter = MaliciousAdapter()
        result = runtime.handle(self.event())
        self.assertEqual(
            result["error"]["code"],
            "adapter_response_reserved_or_unknown_field",
        )

    def test_adapter_mutation_cannot_rebind_document_scope(self) -> None:
        runtime = HandlerRuntime(WorkerConfig.from_env("parser", "test"))

        class MutatingAdapter:
            def self_test(self) -> None:
                return None

            def process(self, input_path, request):
                request["document_id"] = "urn:akmp:doc:other"
                return {
                    "blocks": [
                        {
                            "block_id": "blk_mutated",
                            "origin": "ocr_extracted",
                            "quality_flags": [],
                            "source_refs": [
                                {
                                    "bbox1000": [0, 0, 10, 10],
                                    "document_id": "urn:akmp:doc:other",
                                    "document_version_id": request["document_version_id"],
                                    "page_index0": 0,
                                    "page_number1": 1,
                                }
                            ],
                            "text": "mutated",
                            "type": "paragraph",
                        }
                    ],
                    "generated_claims": [],
                    "warnings": [],
                }

        runtime.adapter = MutatingAdapter()
        result = runtime.handle(self.event())
        self.assertEqual(result["error"]["code"], "adapter_document_scope_mismatch")

    def test_direct_response_has_a_separate_size_cap(self) -> None:
        os.environ["MAX_DIRECT_RESPONSE_BYTES"] = "128"
        result = build_handler("parser", "test")(self.event(text="x" * 500))
        self.assertEqual(result["error"]["code"], "direct_response_too_large")


if __name__ == "__main__":
    unittest.main()
