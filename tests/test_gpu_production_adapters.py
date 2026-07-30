from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any, ClassVar

import pytest
from PIL import Image

ROOT = Path(__file__).parents[1]


def _load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if "runtime" not in sys.modules:
    _load_module("runtime", ROOT / "workers/gpu-common/runtime.py")
PADDLE = _load_module(
    "akc_test_paddleocr_adapter",
    ROOT / "workers/gpu-parser/paddleocr_adapter.py",
)
QWEN = _load_module(
    "akc_test_qwen_adapter",
    ROOT / "workers/gpu-knowledge/qwen_adapter.py",
)


def _write_json(path: Path, value: dict[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _paddle_manifest(tmp_path: Path, revision: str) -> tuple[Path, str]:
    layout = tmp_path / "layout"
    recognition = tmp_path / "recognition"
    layout.mkdir()
    recognition.mkdir()
    layout_file = layout / "model.bin"
    recognition_file = recognition / "model.bin"
    layout_file.write_bytes(b"layout-model")
    recognition_file.write_bytes(b"recognition-model")
    manifest = tmp_path / "manifest.json"
    digest = _write_json(
        manifest,
        {
            "schema_version": "1.0",
            "provider_key": "paddleocr_vl_1_6",
            "pipeline_version": "v1.6",
            "upstream_revision": revision,
            "layout_detection_model_dir": "layout",
            "vl_rec_model_dir": "recognition",
            "files": {
                "layout/model.bin": hashlib.sha256(layout_file.read_bytes()).hexdigest(),
                "recognition/model.bin": hashlib.sha256(recognition_file.read_bytes()).hexdigest(),
            },
        },
    )
    return manifest, digest


class _FakePaddleResult:
    json: ClassVar[dict[str, Any]] = {
        "res": {
            "input_path": "ignored",
            "input_img": "large-raw-media",
            "parsing_res_list": [
                {
                    "block_bbox": [10.0, 20.0, 110.0, 70.0],
                    "block_label": "paragraph_title",
                    "block_content": "근거가 있는 제목",
                    "confidence": 0.99,
                    "token_confidences": [0.99, 0.98, 0.99],
                    "block_id": 0,
                    "block_order": 0,
                }
            ],
        }
    }


class _FakePaddlePipeline:
    kwargs: dict[str, Any]
    predict_kwargs: dict[str, Any]

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        _FakePaddlePipeline.kwargs = kwargs

    def predict(self, **kwargs: Any) -> list[_FakePaddleResult]:
        _FakePaddlePipeline.predict_kwargs = kwargs
        return [_FakePaddleResult()]


def test_paddle_adapter_uses_pinned_local_models_and_preserves_raw_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = "a" * 40
    manifest, digest = _paddle_manifest(tmp_path, revision)
    monkeypatch.setenv("PADDLEOCR_MODEL_MANIFEST", str(manifest))
    monkeypatch.setenv("PADDLEOCR_MODEL_MANIFEST_SHA256", digest)
    monkeypatch.setenv("PADDLEOCR_ENGINE", "paddle")
    monkeypatch.setenv("PADDLEOCR_DEVICE", "gpu:0")
    fake_package = types.ModuleType("paddleocr")
    fake_package.PaddleOCRVL = _FakePaddlePipeline  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "paddleocr", fake_package)

    image_path = tmp_path / "page.png"
    Image.new("RGB", (200, 100), "white").save(image_path)
    adapter = PADDLE.create_adapter(model_revision=revision)
    adapter.self_test()
    result = adapter.process(
        image_path,
        {
            "document_id": "urn:akmp:doc:test",
            "document_version_id": "urn:akmp:doc-version:test-v1",
            "page_index0": 2,
            "options": {
                "max_new_tokens": 1024,
                "orientation_classify": False,
                "unwarp": False,
                "ocr_image_blocks": True,
            },
        },
    )

    assert _FakePaddlePipeline.kwargs["pipeline_version"] == "v1.6"
    assert _FakePaddlePipeline.kwargs["layout_detection_model_dir"].endswith("layout")
    assert _FakePaddlePipeline.predict_kwargs["temperature"] == 0.0
    assert _FakePaddlePipeline.predict_kwargs["use_doc_orientation_classify"] is False
    assert _FakePaddlePipeline.predict_kwargs["use_doc_unwarping"] is False
    assert _FakePaddlePipeline.predict_kwargs["use_ocr_for_image_block"] is True
    assert result["blocks"][0]["type"] == "heading"
    assert result["blocks"][0]["source_refs"][0] == {
        "document_id": "urn:akmp:doc:test",
        "document_version_id": "urn:akmp:doc-version:test-v1",
        "page_index0": 2,
        "page_number1": 3,
        "bbox1000": [50, 200, 550, 700],
    }
    assert result["provider_raw"] == {}
    assert result["provider_metrics"]["raw_output_sha256"].startswith("sha256:")
    assert result["provider_metrics"]["orientation_classify"] is False
    assert result["provider_metrics"]["unwarp"] is False


def test_paddle_adapter_rejects_non_boolean_geometric_options() -> None:
    with pytest.raises(RuntimeError, match="paddleocr_unwarp_invalid"):
        PADDLE._boolean_option({"unwarp": "false"}, "unwarp")


def test_paddle_adapter_fails_closed_on_manifest_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = "b" * 40
    manifest, digest = _paddle_manifest(tmp_path, revision)
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("PADDLEOCR_MODEL_MANIFEST", str(manifest))
    monkeypatch.setenv("PADDLEOCR_MODEL_MANIFEST_SHA256", digest)
    with pytest.raises(RuntimeError, match="paddleocr_model_manifest_checksum_mismatch"):
        PADDLE.create_adapter(model_revision=revision)


def _qwen_attestation(tmp_path: Path, revision: str) -> tuple[Path, str]:
    path = tmp_path / "qwen-attestation.json"
    digest = _write_json(
        path,
        {
            "schema_version": "1.0",
            "model_id": "Qwen/Qwen3.5-4B",
            "upstream_revision": revision,
            "runtime_image_digest": "sha256:" + "c" * 64,
            "adapter_version": "qwen-adapter-1.0.0",
        },
    )
    return path, digest


def _configure_qwen(
    monkeypatch: pytest.MonkeyPatch,
    *,
    attestation: Path,
    attestation_digest: str,
) -> str:
    schema_path = ROOT / "packages/contracts/schemas/knowledge-bundle.schema.json"
    schema_digest = f"sha256:{hashlib.sha256(schema_path.read_bytes()).hexdigest()}"
    pipeline_schema_path = ROOT / "packages/contracts/schemas/knowledge-pipeline-result.schema.json"
    pipeline_schema_digest = (
        f"sha256:{hashlib.sha256(pipeline_schema_path.read_bytes()).hexdigest()}"
    )
    monkeypatch.setenv("QWEN_MODEL_ATTESTATION", str(attestation))
    monkeypatch.setenv("QWEN_MODEL_ATTESTATION_SHA256", attestation_digest)
    monkeypatch.setenv("RUNTIME_IMAGE_DIGEST", "sha256:" + "c" * 64)
    monkeypatch.setenv("ADAPTER_VERSION", "qwen-adapter-1.0.0")
    monkeypatch.setenv("KNOWLEDGE_BUNDLE_SCHEMA", str(schema_path))
    monkeypatch.setenv("KNOWLEDGE_BUNDLE_SCHEMA_SHA256", schema_digest)
    monkeypatch.setenv("KNOWLEDGE_PIPELINE_SCHEMA", str(pipeline_schema_path))
    monkeypatch.setenv(
        "KNOWLEDGE_PIPELINE_SCHEMA_SHA256",
        pipeline_schema_digest,
    )
    return schema_digest


def _qwen_request() -> dict[str, Any]:
    schema_path = ROOT / "packages/contracts/schemas/knowledge-bundle.schema.json"
    return {
        "document_id": "urn:akmp:doc:test",
        "document_version_id": "urn:akmp:doc-version:test-v1",
        "options": {
            "artifact_contract": "akc-knowledge-bundle-1.0.0",
            "prompt_revision": (
                f"sha256:{hashlib.sha256(QWEN._SYSTEM_PROMPT.encode()).hexdigest()}"
            ),
            "knowledge_schema_sha256": (
                f"sha256:{hashlib.sha256(schema_path.read_bytes()).hexdigest()}"
            ),
        },
        "knowledge_input": {
            "schema_version": "knowledge-input-1.0.0",
            "document_id": "urn:akmp:doc:test",
            "document_version_id": "urn:akmp:doc-version:test-v1",
            "title": "테스트 문서",
            "blocks": [
                {
                    "block_id": "blk_source",
                    "text": "검증 가능한 원문",
                    "source_refs": [
                        {
                            "document_id": "urn:akmp:doc:test",
                            "document_version_id": "urn:akmp:doc-version:test-v1",
                            "page_index0": 0,
                            "page_number1": 1,
                            "bbox1000": [0, 0, 1000, 1000],
                        }
                    ],
                }
            ],
        },
    }


def test_qwen_adapter_forces_schema_non_thinking_and_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = "d" * 40
    attestation, digest = _qwen_attestation(tmp_path, revision)
    _configure_qwen(
        monkeypatch,
        attestation=attestation,
        attestation_digest=digest,
    )
    monkeypatch.setenv(
        "QWEN_INFERENCE_URL",
        "http://127.0.0.1:8000/v1/chat/completions",
    )
    captured: list[dict[str, Any] | None] = []

    def fake_request(
        _host: str,
        _port: int,
        method: str,
        _target: str,
        payload: dict[str, Any] | None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        assert timeout > 0
        captured.append(payload)
        if method == "GET":
            return {"data": [{"id": "Qwen/Qwen3.5-4B"}]}
        content = json.dumps(
            {
                "schemaVersion": "knowledge-1.0.0",
                "documentId": "urn:akmp:doc:test",
                "notes": [
                    {
                        "noteId": "document.test",
                        "title": "테스트 문서",
                        "noteType": "document",
                        "contentOrigin": "ai_summarized",
                        "evidenceBlockIds": ["blk_source"],
                        "summary": "검증 가능한 원문",
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
            ensure_ascii=False,
        )
        return {
            "id": "completion-1",
            "model": "Qwen/Qwen3.5-4B",
            "choices": [
                {
                    "message": {"content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 30},
        }

    monkeypatch.setattr(QWEN, "_request_json", fake_request)
    adapter = QWEN.create_adapter(model_revision=revision)
    adapter.self_test()
    result = adapter.process(tmp_path / "unused.bin", _qwen_request())

    provider_request = captured[1]
    assert provider_request is not None
    assert provider_request["chat_template_kwargs"] == {"enable_thinking": False}
    assert provider_request["response_format"]["type"] == "json_schema"
    assert result["knowledge_bundle"]["notes"][0]["evidenceBlockIds"] == ["blk_source"]
    assert result["provider_metrics"]["raw_output_sha256"].startswith("sha256:")
    assert result["provider_raw"]["choices"][0]["message"]["content"]


def test_qwen_adapter_rejects_hallucinated_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = "e" * 40
    attestation, digest = _qwen_attestation(tmp_path, revision)
    _configure_qwen(
        monkeypatch,
        attestation=attestation,
        attestation_digest=digest,
    )

    def fake_request(
        _host: str,
        _port: int,
        _method: str,
        _target: str,
        _payload: dict[str, Any] | None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        assert timeout > 0
        content = json.dumps(
            {
                "schemaVersion": "knowledge-1.0.0",
                "documentId": "urn:akmp:doc:test",
                "notes": [
                    {
                        "noteId": "bad",
                        "title": "Bad",
                        "noteType": "document",
                        "contentOrigin": "ai_inferred",
                        "evidenceBlockIds": ["blk_not_supplied"],
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
            }
        )
        return {
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {},
        }

    monkeypatch.setattr(QWEN, "_request_json", fake_request)
    adapter = QWEN.create_adapter(model_revision=revision)
    with pytest.raises(RuntimeError, match="qwen_schema_output_invalid"):
        adapter.process(tmp_path / "unused.bin", _qwen_request())


def test_qwen_adapter_enforces_staged_schema_and_semantic_merge_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = "9" * 40
    attestation, digest = _qwen_attestation(tmp_path, revision)
    _configure_qwen(
        monkeypatch,
        attestation=attestation,
        attestation_digest=digest,
    )
    pipeline_schema_path = ROOT / "packages/contracts/schemas/knowledge-pipeline-result.schema.json"
    pipeline_schema_digest = (
        f"sha256:{hashlib.sha256(pipeline_schema_path.read_bytes()).hexdigest()}"
    )

    def candidate(
        candidate_id: str,
        block_id: str,
        title: str,
        summary: str,
    ) -> dict[str, Any]:
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
                    "snippet_sha256": hashlib.sha256(snippet.encode()).hexdigest(),
                }
            ],
        }

    request = {
        "document_id": "urn:akmp:doc:test",
        "document_version_id": "urn:akmp:doc-version:test-v1",
        "options": {
            "artifact_contract": "akc-knowledge-pipeline-stage-1.0.0",
            "prompt_revision": (
                f"sha256:{hashlib.sha256(QWEN._SYSTEM_PROMPT.encode()).hexdigest()}"
            ),
            "knowledge_schema_sha256": pipeline_schema_digest,
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
    captured: list[dict[str, Any] | None] = []

    def fake_request(
        _host: str,
        _port: int,
        _method: str,
        _target: str,
        payload: dict[str, Any] | None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        assert timeout > 0
        captured.append(payload)
        content = json.dumps(
            {
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
            }
        )
        return {
            "choices": [
                {
                    "message": {"content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {},
        }

    monkeypatch.setattr(QWEN, "_request_json", fake_request)
    adapter = QWEN.create_adapter(model_revision=revision)
    with pytest.raises(
        RuntimeError,
        match="qwen_pipeline_semantic_merge_unsupported",
    ):
        adapter.process(tmp_path / "unused.bin", request)
    assert captured[0] is not None
    assert (
        captured[0]["response_format"]["json_schema"]["name"] == "akc_knowledge_pipeline_stage_v1"
    )


def test_qwen_adapter_refuses_non_loopback_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = "f" * 40
    attestation, digest = _qwen_attestation(tmp_path, revision)
    _configure_qwen(
        monkeypatch,
        attestation=attestation,
        attestation_digest=digest,
    )
    monkeypatch.setenv(
        "QWEN_INFERENCE_URL",
        "https://external.example/v1/chat/completions",
    )
    with pytest.raises(RuntimeError, match="qwen_inference_endpoint_must_be_loopback"):
        QWEN.create_adapter(model_revision=revision)
