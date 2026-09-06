from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "research" / "tavonel_eval_v2" / "tools"
TESTS = ROOT / "research" / "tavonel_eval_v2" / "tests"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TESTS))

import gpu_successor_runpod_backend as backend  # noqa: E402
from common import sha_file  # noqa: E402
from test_gpu_successor_runtime import (  # noqa: E402
    SHA_A,
    SHA_B,
    SHA_C,
    _bundle,
    _signed_terminal,
)


class MockLifecycle:
    def __init__(self):
        self.resource = None
        self.creates = 0
        self.deletes = 0

    def create(self, request):
        self.creates += 1
        self.resource = {
            "id": "pod-fixture",
            "name": request["name"],
            "gpu_seconds": 1.0,
            "cost_usd": 0.01,
        }
        return self.resource

    def list_by_name(self, _name):
        return [] if self.resource is None else [self.resource]

    def snapshot(self, _resource_id):
        return self.resource

    def delete(self, _resource_id):
        self.deletes += 1
        self.resource = None

    def close(self):
        pass


class MockR2:
    def __init__(self, private, bundle):
        self.values = {}
        self.private = private
        self.bundle = bundle
        self.input_sha = None

    def put_if_absent(self, key, body, sha256):
        self.values[key] = body
        self.input_sha = sha256

    def worker_grants(self, *, input_key, status_key, output_prefix, expires=1800):
        del input_key, expires
        output = b'{"schema":"raw","status":"completed","items":[]}'
        output_sha = "sha256:" + hashlib.sha256(output).hexdigest()
        output_key = f"{output_prefix}/{output_sha[7:]}.json"
        self.values[output_key] = output
        self.values[status_key] = _signed_terminal(
            self.private, self.bundle, self.input_sha, output_key, output_sha
        )
        return {
            "input_get_url": "https://mock.invalid/input",
            "status_put_url": "https://mock.invalid/status",
            "status_put_headers": {"Content-Type": "application/json"},
            "output_post_url": "https://mock.invalid/output",
            "output_post_fields": {"key": output_prefix + "/${filename}"},
            "output_object_prefix": output_prefix + "/",
        }

    def get(self, key):
        if key not in self.values:
            raise KeyError(key)
        return self.values[key]


def test_configured_backend_reaches_mock_controller_only_with_both_exact_authorities(tmp_path):
    bundle_path, bundle, private = _bundle(tmp_path)
    materialized = tmp_path / "materialized.json"
    materialized.write_text('{"frozen":true}', encoding="utf-8")
    lifecycle = MockLifecycle()
    fresh_acceptance = tmp_path / "fresh.json"
    four_link_acceptance = tmp_path / "four.json"
    fresh_acceptance.write_text("fresh", encoding="utf-8")
    four_link_acceptance.write_text("four", encoding="utf-8")
    provisioner = backend.RunpodScientificProvisioner(
        lifecycle=lifecycle,
        objects=MockR2(private, bundle),
        worker_bundle_path=bundle_path,
        worker_bundle_sha256=sha_file(bundle_path),
        materialized_input_path=materialized,
        output_path=tmp_path / "retrieved.json",
        ledger_path=tmp_path / "execution.jsonl",
    )
    base_spec = {
        "model_pin_sha256": SHA_A,
        "runtime_image_digest": "repo/runtime@" + SHA_A,
        "input_contract": {
            "materialized_file_sha256": sha_file(materialized),
            "input_set_digest": SHA_B,
            "manifest_sha256": SHA_C,
        },
    }
    refused = {
        **base_spec,
        "execution_authority": {
            "fresh_study_acceptance": True,
            "fresh_study_acceptance_sha256": sha_file(fresh_acceptance),
            "fresh_study_acceptance_path": str(fresh_acceptance),
            "four_link_acceptance": False,
            "four_link_acceptance_sha256": sha_file(four_link_acceptance),
            "four_link_acceptance_path": str(four_link_acceptance),
        },
    }
    assert provisioner.execution_readiness(refused)["passed"] is False
    assert lifecycle.creates == 0

    accepted = {
        **base_spec,
        "execution_authority": {
            "fresh_study_acceptance": True,
            "fresh_study_acceptance_sha256": sha_file(fresh_acceptance),
            "fresh_study_acceptance_path": str(fresh_acceptance),
            "four_link_acceptance": True,
            "four_link_acceptance_sha256": sha_file(four_link_acceptance),
            "four_link_acceptance_path": str(four_link_acceptance),
        },
    }
    assert provisioner.execution_readiness(accepted)["passed"] is True
    handle = provisioner.provision(accepted)
    assert lifecycle.creates == 0
    result = provisioner.execute_scientific_workload(handle, accepted)
    assert result["status"] == "completed"
    assert lifecycle.creates == lifecycle.deletes == 1
    assert lifecycle.resource is None
    assert handle["torn_down"] is True


def test_backend_configuration_has_no_default_paths_or_floating_bundle(tmp_path):
    bundle_path, bundle, private = _bundle(tmp_path)
    materialized = tmp_path / "materialized.json"
    materialized.write_text("{}", encoding="utf-8")
    provisioner = backend.RunpodScientificProvisioner(
        lifecycle=MockLifecycle(),
        objects=MockR2(private, bundle),
        worker_bundle_path=bundle_path,
        worker_bundle_sha256=sha_file(bundle_path),
        materialized_input_path=materialized,
        output_path=tmp_path / "out.json",
        ledger_path=tmp_path / "ledger.jsonl",
    )
    assert provisioner.bundle["manifest_file_sha256"] == sha_file(bundle_path)
    source = (TOOLS / "gpu_successor_runpod_backend.py").read_text(encoding="utf-8")
    assert "worker_bundle_sha256: str" in source
    assert "latest" not in source.casefold()
