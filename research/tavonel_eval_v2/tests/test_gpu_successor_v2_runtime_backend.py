from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "research" / "tavonel_eval_v2" / "tools"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

import gpu_successor_v2_runpod_backend as backend  # noqa: E402
import gpu_successor_v2_runtime as runtime  # noqa: E402
from common import sha_file  # noqa: E402

from benchmark.v6.ledger import EvidenceLedger  # noqa: E402
from infra.runpod.v6.authorized_budget import AuthorizedSpendBudget  # noqa: E402
from infra.runpod.v6.credentials import RunPodCredentialSet  # noqa: E402

SHA = "sha256:" + "a" * 64


def _signed(
    private: Ed25519PrivateKey, bundle: dict, input_sha: str, output_key: str, output_sha: str
) -> bytes:
    envelope = {
        "schema": runtime.TERMINAL_ENVELOPE_SCHEMA,
        "status": "completed",
        "input_sha256": input_sha,
        "output_key": output_key,
        "output_sha256": output_sha,
        "runtime_attestation": {
            key: bundle[key]
            for key in (
                "bundle_sha256",
                "entrypoint_sha256",
                "scorer_sha256",
                "model_revision_sha256",
                "tokenizer_sha256",
                "vllm_version",
            )
        },
    }
    payload = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    envelope["signature_b64"] = base64.b64encode(private.sign(payload)).decode()
    return json.dumps(envelope).encode()


class Objects:
    def __init__(self, private: Ed25519PrivateKey, bundle: dict) -> None:
        self.private, self.bundle, self.values = private, bundle, {}
        self.input_sha = ""

    def put_if_absent(self, key, body, sha256):
        self.values[key], self.input_sha = body, sha256

    def worker_grants(self, *, input_key, status_key, output_prefix, expires):
        assert input_key in self.values and expires == 20_700
        output = b'{"status":"completed"}'
        output_sha = "sha256:" + hashlib.sha256(output).hexdigest()
        output_key = f"{output_prefix}/{output_sha[7:]}.json"
        self.values[output_key] = output
        self.values[status_key] = _signed(
            self.private, self.bundle, self.input_sha, output_key, output_sha
        )
        return {
            "input_get_url": "https://r2.invalid/input",
            "status_put_url": "https://r2.invalid/status",
            "status_put_headers": {},
            "output_post_url": "https://r2.invalid/output",
            "output_post_fields": {},
            "output_object_prefix": output_prefix + "/",
        }

    def get(self, key):
        if key not in self.values:
            raise KeyError(key)
        return self.values[key]


class Provider:
    def __init__(self, *, timeout_after_create: bool = False):
        self.resource = None
        self.finalized = 0
        self.timeout_after_create = timeout_after_create

    def list_by_name(self, name):
        return [self.resource] if self.resource and self.resource["name"] == name else []

    def create(self, request):
        self.resource = {
            "id": "pod-v2",
            "name": request["name"],
            "gpu_seconds": 2.0,
            "cost_usd": 0.02,
        }
        if self.timeout_after_create:
            raise TimeoutError("ambiguous create timeout")
        return self.resource

    def snapshot(self, _resource_id):
        return self.resource

    def delete_and_finalize(self, _resource_id):
        self.finalized += 1
        self.resource = None
        return {
            "gpu_seconds": 3.0,
            "cost_usd": 0.03,
            "provider_absent": True,
            "source": "provider_predelete_usage_with_delete_absence",
        }


@pytest.mark.parametrize("timeout_after_create", [False, True])
def test_v2_controller_retrieves_authenticated_output_and_finalizes(tmp_path, timeout_after_create):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    bundle = {
        key: SHA
        for key in (
            "bundle_sha256",
            "entrypoint_sha256",
            "scorer_sha256",
            "model_revision_sha256",
            "tokenizer_sha256",
        )
    }
    bundle.update(
        {
            "vllm_version": "0.10.0",
            "facts_digest": SHA,
            "terminal_public_key_b64": base64.b64encode(public).decode(),
        }
    )
    input_path = tmp_path / "inputs.json"
    input_path.write_text("{}", encoding="utf-8")
    authorities = {}
    for prefix in ("sfir4_acceptance", "four_link_acceptance", "protocol_freeze"):
        path = tmp_path / f"{prefix}.json"
        path.write_text(prefix, encoding="utf-8")
        authorities[prefix + "_path"] = str(path)
        authorities[prefix + "_sha256"] = sha_file(path)
    provider = Provider(timeout_after_create=timeout_after_create)
    controller = runtime.V2Controller(
        provider=provider,
        objects=Objects(private, bundle),
        ledger=EvidenceLedger(tmp_path / "ledger.jsonl", cohort_id="v2", run_tag="v6-v2-test"),
        budget=AuthorizedSpendBudget(campaign_id="v2", hard_cap_usd="40"),
    )
    result = controller.execute(
        spec={
            "execution_authority": authorities,
            "materialized_input_sha256": sha_file(input_path),
            "model_pin_sha256": SHA,
            "runtime_image_digest": "repo/image@" + SHA,
        },
        input_path=input_path,
        bundle=bundle,
        output_path=tmp_path / "output.json",
    )
    assert result["status"] == "completed"
    assert result["actual_usage"] == {"gpu_seconds": 3.0, "cost_usd": 0.03}
    assert result["provider_absent"] is True
    assert provider.finalized == 1


def test_runpod_v2_request_is_private_pinned_and_inner_capped(tmp_path):
    protocol = tmp_path / "runtime.yaml"
    protocol.write_text(
        "hardware:\n  gpu_type:\n    value: NVIDIA H200\n  gpu_count:\n    value: 1\n",
        encoding="utf-8",
    )
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/graphql":
            seen.update(json.loads(request.content)["variables"]["input"])
            return httpx.Response(200, json={"data": {"podFindAndDeployOnDemand": {"id": "p"}}})
        return httpx.Response(200, json=[])

    lifecycle = backend.RunpodV2LifecycleTransport(
        credentials=RunPodCredentialSet(("provider-secret",)),
        runtime_protocol_path=protocol,
        signing_private_key_b64="signing-secret",
        worker_bundle_path_in_image="/opt/tavonel/bundle.json",
        model_path_in_image="/opt/tavonel/model",
        model_manifest_path_in_image="/opt/tavonel/model-manifest.json",
        tokenizer_path_in_image="/opt/tavonel/tokenizer",
        tokenizer_manifest_path_in_image="/opt/tavonel/tokenizer-manifest.json",
        transport=httpx.MockTransport(handler),
    )
    grants = {
        "input_get_url": "https://r2.invalid/i",
        "status_put_url": "https://r2.invalid/s",
        "status_put_headers": {},
        "output_post_url": "https://r2.invalid/o",
        "output_post_fields": {},
        "output_object_prefix": "out/",
    }
    lifecycle.create(
        {
            "name": "v2",
            "runtime_image_digest": "repo/image@" + SHA,
            "input_sha256": SHA,
            "worker_bundle": {"facts_digest": SHA, "entrypoint": ["python", "worker.py"]},
            "worker_transport": grants,
        }
    )
    assert seen["cloudType"] == "SECURE"
    assert seen["startSsh"] is seen["supportPublicIp"] is False
    assert seen["imageName"] == "repo/image@" + SHA
    assert seen["env"]["TAVONEL_TERMINAL_PRIVATE_KEY_B64"] == "signing-secret"
    assert "provider-secret" not in json.dumps(seen)
    lifecycle.close()


def test_runpod_v2_final_usage_comes_from_delete_response(tmp_path):
    protocol = tmp_path / "runtime.yaml"
    protocol.write_text(
        "hardware:\n  gpu_type:\n    value: NVIDIA H200\n  gpu_count:\n    value: 1\n",
        encoding="utf-8",
    )
    deleted = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal deleted
        if request.method == "DELETE":
            deleted = True
            return httpx.Response(204)
        if request.url.path.endswith("/pods/p"):
            if deleted:
                return httpx.Response(404)
            return httpx.Response(200, json={"uptimeSeconds": 8, "costPerHr": 2.0})
        return httpx.Response(200, json=[])

    lifecycle = backend.RunpodV2LifecycleTransport(
        credentials=RunPodCredentialSet(("provider-secret",)),
        runtime_protocol_path=protocol,
        signing_private_key_b64="signing-secret",
        worker_bundle_path_in_image="/opt/tavonel/bundle.json",
        model_path_in_image="/opt/tavonel/model",
        model_manifest_path_in_image="/opt/tavonel/model-manifest.json",
        tokenizer_path_in_image="/opt/tavonel/tokenizer",
        tokenizer_manifest_path_in_image="/opt/tavonel/tokenizer-manifest.json",
        transport=httpx.MockTransport(handler),
    )
    final = lifecycle.delete_and_finalize("p")
    assert final["gpu_seconds"] == 8
    assert final["source"] == "provider_predelete_usage_with_delete_absence"
    assert final["provider_absent"] is True
    assert final["absence_observations"] == 3
    lifecycle.close()
