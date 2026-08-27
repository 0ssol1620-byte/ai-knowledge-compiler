from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

NS = Path(__file__).resolve().parents[1]
TOOLS = NS / "tools"
sys.path.insert(0, str(TOOLS))

import freeze_gpu_successor_v2_worker_bundle as freeze  # noqa: E402
import gpu_successor_v2_scorer as scorer  # noqa: E402
import gpu_successor_v2_worker as worker  # noqa: E402

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64


def _request() -> dict:
    return {
        "system_prompt": "Answer from sources.",
        "user_prompt": "Question and sources",
        "decoding": {"temperature": 0.0, "strategy": "greedy", "thinking": "off"},
        "max_new_tokens": 256,
    }


def _materialized() -> dict:
    items = [
        {
            "fact_id": f"fact-{index:03d}",
            "lineage_id": f"lineage-{index:03d}",
            "kind": "LANGUAGE",
            "current_expected_value": {"scope": "document", "tag": "en-us"},
            "arms": {
                "CURRENT_TYPED": _request(),
                "STALE_TYPED": _request(),
                "CURRENT_TEXT_ONLY": _request(),
            },
        }
        for index in range(450)
    ]
    return {
        "schema": "tavonel.v2.successor_materialized_inputs.v2",
        "study_id": freeze.STUDY_ID,
        "set_digest": SHA_A,
        "item_count": len(items),
        "items": items,
    }


def _bundle(private: Ed25519PrivateKey) -> dict:
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return {
        "bundle_sha256": SHA_A,
        "entrypoint_sha256": SHA_B,
        "scorer_sha256": "sha256:" + "c" * 64,
        "model_revision_sha256": "sha256:" + "d" * 64,
        "tokenizer_sha256": "sha256:" + "e" * 64,
        "vllm_version": "0.10.2",
        "terminal_public_key_b64": base64.b64encode(public).decode("ascii"),
    }


class MemoryTransport:
    def __init__(self, input_body: bytes) -> None:
        self.input_body = input_body
        self.output: bytes | None = None
        self.output_key: str | None = None
        self.status: bytes | None = None

    def fetch_input(self) -> bytes:
        return self.input_body

    def upload_output(self, filename: str, body: bytes) -> str:
        self.output = body
        self.output_key = "gpu-successor/outputs/test/" + filename
        return self.output_key

    def publish_status(self, body: bytes) -> None:
        self.status = body


def test_scorer_uses_canonical_typed_value_and_keeps_refusal_distinct():
    expected = {"tag": "en-us", "scope": "document"}
    assert (
        scorer.classify_answer('{"scope":"document", "tag":"en-us"}', expected)
        == scorer.ANSWER_MATCHES_CURRENT
    )
    assert scorer.classify_answer("not stated.", expected) == scorer.ANSWER_REFUSED
    assert scorer.classify_answer('{"scope":"link","tag":"en-us"}', expected) == scorer.ANSWER_OTHER


def test_scorer_refuses_to_reconstruct_ground_truth_from_prompt():
    with pytest.raises(scorer.ScoringRefused, match="cannot be reconstructed"):
        scorer.expected_value({"arms": {}})


def test_worker_runs_injected_inference_uploads_raw_output_and_signed_terminal():
    private = Ed25519PrivateKey.generate()
    materialized = worker.canonical_bytes(_materialized())
    transport = MemoryTransport(materialized)
    calls: list[dict] = []

    def deterministic_inference(request: dict) -> str:
        calls.append(request)
        return '{"tag":"en-us","scope":"document"}'

    result = worker.run_worker(
        transport=transport,
        inference=deterministic_inference,
        private_key=private,
        bundle=_bundle(private),
        expected_input_sha256=worker.sha_bytes(materialized),
        determinism_repeats=2,
    )
    assert len(calls) == 2700
    assert transport.output is not None and transport.status is not None
    artifact = json.loads(transport.output)
    assert artifact["status"] == "completed"
    assert artifact["inference"]["target_lineages"] == 450
    for arm in worker.ARMS:
        repetitions = artifact["items"][0]["arms"][arm]["repetitions"]
        assert [entry["class"] for entry in repetitions] == [
            scorer.ANSWER_MATCHES_CURRENT,
            scorer.ANSWER_MATCHES_CURRENT,
        ]
    envelope = json.loads(transport.status)
    signature = base64.b64decode(envelope.pop("signature_b64"), validate=True)
    private.public_key().verify(signature, worker.canonical_bytes(envelope))
    assert envelope["output_sha256"] == worker.sha_bytes(transport.output)
    assert result["terminal_envelope"]["output_key"] == transport.output_key


def test_worker_fails_before_inference_when_input_digest_drifts():
    private = Ed25519PrivateKey.generate()
    body = worker.canonical_bytes(_materialized())
    transport = MemoryTransport(body)
    called = False

    def inference(_request: dict) -> str:
        nonlocal called
        called = True
        return "x"

    with pytest.raises(worker.WorkerError, match="content digest"):
        worker.run_worker(
            transport=transport,
            inference=inference,
            private_key=private,
            bundle=_bundle(private),
            expected_input_sha256=SHA_A,
            determinism_repeats=1,
        )
    assert called is False
    assert transport.output is None and transport.status is None


def test_local_vllm_client_refuses_any_non_loopback_endpoint():
    with pytest.raises(worker.WorkerError, match="loopback"):
        worker.LocalVllmClient(base_url="https://provider.example", model="pinned/model")


def test_bundle_builder_rehashes_exact_paths_and_contains_no_private_key(tmp_path):
    worker_path = tmp_path / "worker.py"
    scorer_path = tmp_path / "scorer.py"
    worker_path.write_text("print('worker')\n", encoding="utf-8")
    scorer_path.write_text("print('scorer')\n", encoding="utf-8")
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    bundle = freeze.build_bundle(
        worker_path=worker_path,
        worker_expected_sha256=freeze.sha_file(worker_path),
        worker_logical_path="tools/worker.py",
        scorer_path=scorer_path,
        scorer_expected_sha256=freeze.sha_file(scorer_path),
        scorer_logical_path="tools/scorer.py",
        terminal_public_key_b64=base64.b64encode(public).decode("ascii"),
        model_repository="Qwen/pinned",
        model_revision_sha256=SHA_A,
        tokenizer_sha256=SHA_B,
        vllm_version="0.10.2",
        determinism_repeats=2,
    )
    assert bundle["entrypoint_sha256"] == freeze.sha_file(worker_path)
    assert bundle["scorer_sha256"] == freeze.sha_file(scorer_path)
    assert "TAVONEL_TERMINAL_PRIVATE_KEY_B64" not in json.dumps(bundle)
    assert bundle["facts_digest"] == freeze.canonical_sha(
        {key: value for key, value in bundle.items() if key != "facts_digest"}
    )
    worker.verify_runtime_bundle(bundle, worker_path=worker_path, scorer_path=scorer_path)


def test_runtime_bundle_verification_detects_baked_file_drift(tmp_path):
    worker_path = tmp_path / "worker.py"
    scorer_path = tmp_path / "scorer.py"
    worker_path.write_text("worker-v1", encoding="utf-8")
    scorer_path.write_text("scorer-v1", encoding="utf-8")
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    bundle = freeze.build_bundle(
        worker_path=worker_path,
        worker_expected_sha256=freeze.sha_file(worker_path),
        worker_logical_path="tools/worker.py",
        scorer_path=scorer_path,
        scorer_expected_sha256=freeze.sha_file(scorer_path),
        scorer_logical_path="tools/scorer.py",
        terminal_public_key_b64=base64.b64encode(public).decode("ascii"),
        model_repository="Qwen/pinned",
        model_revision_sha256=SHA_A,
        tokenizer_sha256=SHA_B,
        vllm_version="0.10.2",
        determinism_repeats=2,
    )
    scorer_path.write_text("scorer-drift", encoding="utf-8")
    with pytest.raises(worker.WorkerError, match="scorer_sha256"):
        worker.verify_runtime_bundle(bundle, worker_path=worker_path, scorer_path=scorer_path)


def test_bundle_builder_refuses_hash_drift_and_exclusive_overwrite(tmp_path):
    artifact = tmp_path / "worker.py"
    artifact.write_text("x", encoding="utf-8")
    with pytest.raises(freeze.BundleFreezeRefused, match="hash drifted"):
        freeze._verified_artifact(artifact, SHA_A, "tools/worker.py")
    output = tmp_path / "bundle.json"
    freeze.write_exclusive(output, {"safe": True})
    with pytest.raises(freeze.BundleFreezeRefused, match="already exists"):
        freeze.write_exclusive(output, {"safe": True})


def test_image_local_artifact_manifest_is_complete_and_content_verified(tmp_path):
    root = tmp_path / "model"
    root.mkdir()
    artifact = root / "weights.bin"
    artifact.write_bytes(b"weights")
    files = [{"path": "weights.bin", "sha256": worker.sha_bytes(b"weights")}]
    digest = worker.sha_bytes(worker.canonical_bytes(files))
    manifest = tmp_path / "model-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "tavonel.v2.model_artifact_manifest.v1",
                "files": files,
                "files_digest": digest,
            }
        ),
        encoding="utf-8",
    )
    worker.verify_image_artifact_manifest(
        root=root,
        manifest_path=manifest,
        schema="tavonel.v2.model_artifact_manifest.v1",
        expected_files_digest=digest,
    )
    artifact.write_bytes(b"drift")
    with pytest.raises(worker.WorkerError, match="file drifted"):
        worker.verify_image_artifact_manifest(
            root=root,
            manifest_path=manifest,
            schema="tavonel.v2.model_artifact_manifest.v1",
            expected_files_digest=digest,
        )
