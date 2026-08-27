from __future__ import annotations

import base64
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "research" / "tavonel_eval_v2" / "tools"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

import gpu_successor_runtime as runtime  # noqa: E402
from common import canonical_sha, sha_file  # noqa: E402
from gpu_successor_preflight import STUDY_ID  # noqa: E402

from benchmark.v6.ledger import EvidenceLedger  # noqa: E402
from infra.runpod.v6.authorized_budget import AuthorizedSpendBudget  # noqa: E402

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
SHA_D = "sha256:" + "d" * 64
SHA_E = "sha256:" + "e" * 64


def _bundle(tmp_path: Path):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    body: dict[str, Any] = {
        "schema": runtime.WORKER_BUNDLE_SCHEMA,
        "study_id": STUDY_ID,
        "bundle_sha256": SHA_A,
        "entrypoint": ["python", "-m", "tavonel_gpu_successor.worker"],
        "entrypoint_sha256": SHA_B,
        "scorer_sha256": SHA_C,
        "model_revision_sha256": SHA_D,
        "tokenizer_sha256": SHA_E,
        "vllm_version": "0.27.1",
        "terminal_public_key_b64": base64.b64encode(public).decode(),
    }
    body["facts_digest"] = canonical_sha(body)
    path = tmp_path / "worker-bundle.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path, runtime.load_worker_bundle(path, sha_file(path)), private


def _signed_terminal(private, bundle, input_sha, output_key, output_sha):
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
    payload = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    envelope["signature_b64"] = base64.b64encode(private.sign(payload)).decode()
    return json.dumps(envelope, sort_keys=True).encode()


class MemoryObjects:
    def __init__(self):
        self.values: dict[str, bytes] = {}
        self.puts = 0

    def put_if_absent(self, key, body, sha256):
        assert runtime._sha_bytes(body) == sha256
        if key in self.values and self.values[key] != body:
            raise RuntimeError("content-address collision")
        self.values.setdefault(key, body)
        self.puts += 1

    def get(self, key):
        if key not in self.values:
            raise KeyError(key)
        return self.values[key]


class MockProvider:
    def __init__(self, *, usage=None, ambiguous=False, duplicate=False):
        self.resources: dict[str, dict[str, Any]] = {}
        self.usage = usage or {"gpu_seconds": 12.0, "cost_usd": 0.05}
        self.ambiguous = ambiguous
        self.duplicate = duplicate
        self.create_calls = 0
        self.delete_calls = 0

    def create(self, request):
        self.create_calls += 1
        resource = {"id": "pod-1", "name": request["name"], **self.usage}
        self.resources["pod-1"] = resource
        if self.ambiguous:
            raise TimeoutError("write outcome unknown")
        return resource

    def list_by_name(self, name):
        found = [value for value in self.resources.values() if value["name"] == name]
        return found * 2 if self.duplicate and found else found

    def snapshot(self, resource_id):
        return self.resources.get(resource_id)

    def delete(self, resource_id):
        self.delete_calls += 1
        self.resources.pop(resource_id, None)


def _controller(tmp_path, provider, objects, *, cap=Decimal("40")):
    ledger = EvidenceLedger(
        tmp_path / "gpu.jsonl", cohort_id="gpu-successor-study", run_tag="v6-gpu-successor-test"
    )
    budget = AuthorizedSpendBudget(campaign_id="gpu-successor", hard_cap_usd="40")
    return runtime.GpuSuccessorController(
        provider=provider,
        objects=objects,
        ledger=ledger,
        budget=budget,
        limits=runtime.RuntimeLimits(
            maximum_seconds=21600, maximum_cost_usd=cap, poll_seconds=0.001
        ),
        wait=lambda _seconds: None,
    )


def _run(tmp_path, *, provider=None, mutate_terminal=None):
    bundle_path, bundle, private = _bundle(tmp_path)
    del bundle_path
    input_path = tmp_path / "inputs.json"
    input_path.write_text('{"frozen":true}', encoding="utf-8")
    input_sha = sha_file(input_path)
    output = b'{"schema":"raw","status":"completed"}'
    output_sha = runtime._sha_bytes(output)
    run_suffix = canonical_sha(
        {
            "study_id": STUDY_ID,
            "input_sha256": input_sha,
            "worker_bundle_sha256": bundle["bundle_sha256"],
            "model_pin_sha256": SHA_A,
        }
    )[7:23]
    output_key = f"gpu-successor/outputs/{run_suffix}/{output_sha[7:]}.json"
    status_key = "gpu-successor/status/" + run_suffix + ".json"
    objects = MemoryObjects()
    objects.values[output_key] = output
    terminal = json.loads(_signed_terminal(private, bundle, input_sha, output_key, output_sha))
    if mutate_terminal:
        mutate_terminal(terminal)
    objects.values[status_key] = json.dumps(terminal).encode()
    provider = provider or MockProvider()
    controller = _controller(tmp_path, provider, objects)
    fresh_acceptance = tmp_path / "fresh-acceptance.json"
    four_link_acceptance = tmp_path / "four-link-acceptance.json"
    fresh_acceptance.write_text("fresh", encoding="utf-8")
    four_link_acceptance.write_text("four-link", encoding="utf-8")
    result = controller.execute(
        spec={
            "execution_authority": {
                "fresh_study_acceptance": True,
                "four_link_acceptance": True,
                "fresh_study_acceptance_sha256": sha_file(fresh_acceptance),
                "fresh_study_acceptance_path": str(fresh_acceptance),
                "four_link_acceptance_sha256": sha_file(four_link_acceptance),
                "four_link_acceptance_path": str(four_link_acceptance),
            },
            "input_contract": {"materialized_file_sha256": input_sha},
            "model_pin_sha256": SHA_A,
        },
        input_path=input_path,
        bundle=bundle,
        output_path=tmp_path / "retrieved.json",
    )
    return result, controller, provider, objects


def test_mock_transport_completes_with_zero_real_spend_and_absence_proof(tmp_path):
    result, controller, provider, objects = _run(tmp_path)
    assert result["status"] == "completed"
    assert result["provider_absent"] is True
    assert provider.create_calls == provider.delete_calls == 1
    assert provider.resources == {}
    assert Decimal(result["budget"]["settled_usd"]) == Decimal("0.050000")
    assert objects.puts == 1
    assert controller.ledger.latest("endpoint.provider_absent.v1") is not None


def test_ambiguous_create_is_reconciled_without_replaying_paid_write(tmp_path):
    provider = MockProvider(ambiguous=True)
    result, _controller_value, provider, _objects = _run(tmp_path, provider=provider)
    assert result["status"] == "completed"
    assert provider.create_calls == 1


def test_forged_terminal_status_fails_and_still_deletes(tmp_path):
    provider = MockProvider()
    with pytest.raises(runtime.RuntimeControlError, match="authentication"):
        _run(tmp_path, provider=provider, mutate_terminal=lambda body: body.update(status="failed"))
    assert provider.delete_calls == 1
    assert provider.resources == {}


def test_live_dollar_kill_switch_fires_before_accepting_output(tmp_path):
    provider = MockProvider(usage={"gpu_seconds": 1.0, "cost_usd": 40.0})
    with pytest.raises(runtime.RuntimeControlError, match="dollar kill switch"):
        _run(tmp_path, provider=provider)
    assert provider.delete_calls == 1
    assert provider.resources == {}


def test_both_fresh_acceptances_are_mandatory_before_upload_or_create(tmp_path):
    _path, bundle, _private = _bundle(tmp_path)
    input_path = tmp_path / "inputs.json"
    input_path.write_text("{}", encoding="utf-8")
    provider = MockProvider()
    objects = MemoryObjects()
    controller = _controller(tmp_path, provider, objects)
    fresh_acceptance = tmp_path / "fresh.json"
    four_link_acceptance = tmp_path / "four.json"
    fresh_acceptance.write_text("fresh", encoding="utf-8")
    four_link_acceptance.write_text("four", encoding="utf-8")
    with pytest.raises(runtime.RuntimeControlError, match="both required"):
        controller.execute(
            spec={
                "execution_authority": {
                    "fresh_study_acceptance": True,
                    "four_link_acceptance": False,
                    "fresh_study_acceptance_sha256": sha_file(fresh_acceptance),
                    "fresh_study_acceptance_path": str(fresh_acceptance),
                    "four_link_acceptance_sha256": sha_file(four_link_acceptance),
                    "four_link_acceptance_path": str(four_link_acceptance),
                }
            },
            input_path=input_path,
            bundle=bundle,
            output_path=tmp_path / "out.json",
        )
    assert provider.create_calls == 0
    assert objects.puts == 0


def test_worker_bundle_manifest_hash_and_facts_are_both_enforced(tmp_path):
    path, _bundle_value, _private = _bundle(tmp_path)
    body = json.loads(path.read_text(encoding="utf-8"))
    body["vllm_version"] = "floating"
    path.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(runtime.RuntimeControlError, match="facts_digest"):
        runtime.load_worker_bundle(path, sha_file(path))


def test_duplicate_reconciliation_is_fail_closed(tmp_path):
    provider = MockProvider(ambiguous=True, duplicate=True)
    with pytest.raises(runtime.RuntimeControlError, match="could not be reconciled"):
        _run(tmp_path, provider=provider)
    assert provider.create_calls == 1
