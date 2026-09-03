from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from infra.runpod.v6.direct_oci_bake import bake


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _put_blob(root: Path, data: bytes) -> str:
    digest = _sha(data)
    path = root / "blobs" / "sha256" / digest.split(":", 1)[1]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return digest


def _base_oci(root: Path, source_digest: str) -> tuple[str, list[str]]:
    root.mkdir(parents=True)
    (root / "oci-layout").write_text('{"imageLayoutVersion":"1.0.0"}\n', encoding="utf-8")
    raw_layer = b"base-layer\n"
    compressed_layer = gzip.compress(raw_layer, mtime=0)
    layer_digest = _put_blob(root, compressed_layer)
    diff_id = _sha(raw_layer)
    config = {
        "architecture": "amd64",
        "os": "linux",
        "config": {
            "Env": ["PATH=/usr/bin", "UNCHANGED=yes"],
            "Entrypoint": ["vllm", "serve"],
            "Cmd": None,
        },
        "rootfs": {"type": "layers", "diff_ids": [diff_id]},
        "history": [],
    }
    config_bytes = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    config_digest = _put_blob(root, config_bytes)
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {
            "mediaType": "application/vnd.oci.image.config.v1+json",
            "digest": config_digest,
            "size": len(config_bytes),
        },
        "layers": [
            {
                "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                "digest": layer_digest,
                "size": len(compressed_layer),
            }
        ],
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest_digest = _put_blob(root, manifest_bytes)
    index = {
        "schemaVersion": 2,
        "manifests": [
            {
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "digest": manifest_digest,
                "size": len(manifest_bytes),
                "platform": {"architecture": "amd64", "os": "linux"},
                "annotations": {"org.opencontainers.image.ref.name": "vllm-base"},
            }
        ],
    }
    (root / "index.json").write_text(json.dumps(index), encoding="utf-8")
    (root / "download-receipt.json").write_text(
        json.dumps({"source_multiarch_digest": source_digest}), encoding="utf-8"
    )
    return manifest_digest, [layer_digest]


def _fixture(tmp_path: Path) -> dict[str, Path | str]:
    source_digest = "sha256:" + "1" * 64
    base = tmp_path / "base"
    _base_oci(base, source_digest)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    model = b"model-payload"
    (snapshot / "model.safetensors").write_bytes(model)
    (snapshot / "config.json").write_text('{"model":"ovis"}\n', encoding="utf-8")
    model_sha = hashlib.sha256(model).hexdigest()
    revision = "a" * 40
    snapshot_receipt = snapshot / "snapshot-receipt.json"
    snapshot_receipt.write_text(
        json.dumps(
            {
                "resolved_revision": revision,
                "model_safetensors_sha256": "sha256:" + model_sha,
            }
        ),
        encoding="utf-8",
    )
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "\n".join(
            [
                f"ARG BASE_IMAGE=docker.io/vllm/vllm-openai@{source_digest}",
                "FROM ${BASE_IMAGE}",
                f"ARG MODEL_REVISION={revision}",
                f"ARG MODEL_SAFETENSORS_SHA256={model_sha}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    verify = tmp_path / "verify-runtime.sh"
    start = tmp_path / "start-ssh.sh"
    qualification = tmp_path / "qualification_http.py"
    verify.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    start.write_text("#!/bin/sh\nexec true\n", encoding="utf-8")
    qualification.write_text("print('qualification')\n", encoding="utf-8")
    return {
        "source_digest": source_digest,
        "base": base,
        "snapshot": snapshot,
        "snapshot_receipt": snapshot_receipt,
        "dockerfile": dockerfile,
        "verify": verify,
        "start": start,
        "qualification": qualification,
    }


def _run(fx: dict[str, Path | str], tmp_path: Path, name: str) -> dict[str, object]:
    out = tmp_path / name
    return bake(
        base_oci=fx["base"],  # type: ignore[arg-type]
        base_tag="vllm-base",
        output_oci=out,
        output_tag="ovis-baked",
        model_snapshot=fx["snapshot"],  # type: ignore[arg-type]
        model_snapshot_receipt=fx["snapshot_receipt"],  # type: ignore[arg-type]
        dockerfile=fx["dockerfile"],  # type: ignore[arg-type]
        verify_script=fx["verify"],  # type: ignore[arg-type]
        start_script=fx["start"],  # type: ignore[arg-type]
        qualification_script=fx["qualification"],  # type: ignore[arg-type]
        attestation_out=tmp_path / f"{name}.attestation.json",
    )


def _descriptor(root: Path, tag: str) -> dict[str, object]:
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    return next(
        item
        for item in index["manifests"]
        if item.get("annotations", {}).get("org.opencontainers.image.ref.name") == tag
    )


def _json_blob(root: Path, digest: str) -> dict[str, object]:
    return json.loads(
        (root / "blobs" / "sha256" / digest.split(":", 1)[1]).read_text(encoding="utf-8")
    )


def test_daemonless_bake_preserves_base_and_appends_one_layer(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    base_index_before = (fx["base"] / "index.json").read_bytes()  # type: ignore[operator]
    attestation = _run(fx, tmp_path, "out")
    out = tmp_path / "out"
    assert (fx["base"] / "index.json").read_bytes() == base_index_before  # type: ignore[operator]
    assert len(_descriptor(out, "vllm-base")) > 0
    baked = _descriptor(out, "ovis-baked")
    manifest = _json_blob(out, str(baked["digest"]))
    assert len(manifest["layers"]) == 2  # type: ignore[arg-type]
    assert manifest["layers"][0]["digest"] == attestation["base_layers_preserved"][0]  # type: ignore[index]
    config = _json_blob(out, str(manifest["config"]["digest"]))  # type: ignore[index]
    assert len(config["rootfs"]["diff_ids"]) == 2  # type: ignore[index]
    assert config["config"]["Entrypoint"] == ["/opt/folynta/start-ssh.sh"]  # type: ignore[index]
    assert config["config"]["ExposedPorts"] == {"22/tcp": {}, "8001/tcp": {}}  # type: ignore[index]
    assert "runtime_dependency_verification=required_at_gpu_qualification\n" in gzip.decompress(
        (out / "blobs" / "sha256" / str(attestation["new_layer_digest"]).split(":", 1)[1]).read_bytes()
    ).decode("latin-1")


def test_daemonless_bake_is_byte_deterministic_for_same_inputs(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    first = _run(fx, tmp_path, "out-a")
    second = _run(fx, tmp_path, "out-b")
    assert first["new_layer_digest"] == second["new_layer_digest"]
    assert first["new_layer_diff_id"] == second["new_layer_diff_id"]
    assert first["output_config_digest"] == second["output_config_digest"]
    assert first["output_manifest_digest"] == second["output_manifest_digest"]


def test_daemonless_bake_fails_closed_on_model_pin_mismatch(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    receipt = fx["snapshot_receipt"]  # type: ignore[assignment]
    raw = json.loads(receipt.read_text(encoding="utf-8"))
    raw["model_safetensors_sha256"] = "sha256:" + "0" * 64
    receipt.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RuntimeError, match="snapshot SHA"):
        _run(fx, tmp_path, "out")
