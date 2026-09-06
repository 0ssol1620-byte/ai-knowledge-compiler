"""Deterministic daemonless Ovis runtime bake over a verified OCI base.

This builder never unpacks or rewrites the immutable base layers.  It hard-links
(or copies when hard-linking is unavailable) the verified base blob store into a
new OCI layout, appends one deterministic layer containing the pinned Ovis model
snapshot and TAVONEL runtime files, writes a new OCI config/manifest/tag, and
emits a parity attestation.

The resulting image still requires the normal paid GPU runtime qualification.
In particular, build assembly does not claim that the base dependency versions
are correct; ``qualification_http.py`` measures those versions inside the final
image and fails closed before producing runtime-verification evidence.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from benchmark.v6.contracts import canonical_sha256

OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"
OCI_LAYER_GZIP = "application/vnd.oci.image.layer.v1.tar+gzip"
SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
MODEL_REV = re.compile(r"^ARG MODEL_REVISION=([0-9a-f]{40,64})\s*$", re.M)
MODEL_SHA = re.compile(r"^ARG MODEL_SAFETENSORS_SHA256=([0-9a-f]{64})\s*$", re.M)
BASE_IMAGE = re.compile(r"^ARG BASE_IMAGE=(\S+@sha256:[0-9a-f]{64})\s*$", re.M)


@dataclass(frozen=True, slots=True)
class BakePins:
    base_image: str
    model_revision: str
    model_sha256: str


def _canonical(value: object) -> bytes:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return encoded.encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _read_pins(dockerfile: Path) -> BakePins:
    text = dockerfile.read_text(encoding="utf-8")
    base = BASE_IMAGE.search(text)
    revision = MODEL_REV.search(text)
    model = MODEL_SHA.search(text)
    if not base or not revision or not model:
        raise ValueError("Dockerfile runtime pins are incomplete")
    return BakePins(base.group(1), revision.group(1), model.group(1))


def _blob(root: Path, digest: str) -> Path:
    if not SHA.fullmatch(digest):
        raise ValueError(f"invalid OCI digest: {digest}")
    return root / "blobs" / "sha256" / digest.split(":", 1)[1]


def _read_json_blob(root: Path, digest: str) -> dict[str, Any]:
    return json.loads(_blob(root, digest).read_text(encoding="utf-8"))


def _find_tag(index: dict[str, Any], tag: str) -> dict[str, Any]:
    matches = [
        item
        for item in index.get("manifests", [])
        if (item.get("annotations") or {}).get("org.opencontainers.image.ref.name") == tag
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one OCI descriptor for {tag!r}, found {len(matches)}")
    return dict(matches[0])


def _copy_layout(base: Path, out: Path) -> None:
    if out.exists():
        raise FileExistsError(f"output OCI layout already exists: {out}")
    (out / "blobs" / "sha256").mkdir(parents=True)
    shutil.copy2(base / "oci-layout", out / "oci-layout")
    # Base blobs are immutable content-addressed files. Hard links avoid another
    # 11+ GiB copy while keeping a distinct index/manifest namespace.
    for source in sorted((base / "blobs" / "sha256").iterdir()):
        target = out / "blobs" / "sha256" / source.name
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
    shutil.copy2(base / "index.json", out / "index.json")


def _tar_info(
    path: str, *, mode: int, size: int = 0, kind: bytes = tarfile.REGTYPE
) -> tarfile.TarInfo:
    info = tarfile.TarInfo(path)
    info.type = kind
    info.mode = mode
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = 0
    info.size = size
    return info


def _add_dir(tar: tarfile.TarFile, path: str, mode: int = 0o755) -> None:
    normalized = str(PurePosixPath(path)).lstrip("/").rstrip("/") + "/"
    tar.addfile(_tar_info(normalized, mode=mode, kind=tarfile.DIRTYPE))


def _add_bytes(tar: tarfile.TarFile, path: str, data: bytes, mode: int) -> None:
    normalized = str(PurePosixPath(path)).lstrip("/")
    tar.addfile(_tar_info(normalized, mode=mode, size=len(data)), io.BytesIO(data))


def _build_layer(
    *,
    snapshot: Path,
    verify_script: Path,
    start_script: Path,
    qualification_script: Path,
    baked_receipt: bytes,
) -> tuple[bytes, str, str, dict[str, str]]:
    uncompressed = io.BytesIO()
    file_hashes: dict[str, str] = {}
    with tarfile.open(fileobj=uncompressed, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for directory, mode in (
            ("opt", 0o755),
            ("opt/folynta", 0o755),
            ("opt/folynta/models", 0o755),
            ("opt/folynta/models/OvisOCR2", 0o755),
            ("run", 0o755),
            ("run/sshd", 0o755),
            ("root", 0o700),
            ("root/.ssh", 0o700),
        ):
            _add_dir(tar, directory, mode)
        for source in sorted(path for path in snapshot.rglob("*") if path.is_file()):
            rel = source.relative_to(snapshot).as_posix()
            data = source.read_bytes()
            target = f"opt/folynta/models/OvisOCR2/{rel}"
            _add_bytes(tar, target, data, 0o444)
            file_hashes["/" + target] = _sha_bytes(data)
        for source, target, mode in (
            (verify_script, "opt/folynta/verify-runtime.sh", 0o555),
            (start_script, "opt/folynta/start-ssh.sh", 0o555),
            (qualification_script, "opt/folynta/qualification-http.py", 0o444),
        ):
            data = source.read_bytes()
            _add_bytes(tar, target, data, mode)
            file_hashes["/" + target] = _sha_bytes(data)
        _add_bytes(tar, "opt/folynta/baked-runtime-receipt.txt", baked_receipt, 0o444)
        file_hashes["/opt/folynta/baked-runtime-receipt.txt"] = _sha_bytes(baked_receipt)

    raw = uncompressed.getvalue()
    diff_id = _sha_bytes(raw)
    compressed_buffer = io.BytesIO()
    with gzip.GzipFile(
        filename="", mode="wb", fileobj=compressed_buffer, mtime=0, compresslevel=6
    ) as gz:
        gz.write(raw)
    compressed = compressed_buffer.getvalue()
    return compressed, diff_id, _sha_bytes(compressed), file_hashes


def _merge_env(existing: Iterable[str], updates: dict[str, str]) -> list[str]:
    values: dict[str, str] = {}
    order: list[str] = []
    for item in existing:
        key, sep, value = item.partition("=")
        if not sep:
            continue
        if key not in values:
            order.append(key)
        values[key] = value
    for key, value in updates.items():
        if key not in values:
            order.append(key)
        values[key] = value
    return [f"{key}={values[key]}" for key in order]


def _write_blob(root: Path, data: bytes) -> str:
    digest = _sha_bytes(data)
    path = _blob(root, digest)
    if path.exists():
        if _sha_file(path) != digest:
            raise RuntimeError(f"existing OCI blob hash mismatch: {digest}")
    else:
        path.write_bytes(data)
    return digest


def bake(
    *,
    base_oci: Path,
    base_tag: str,
    output_oci: Path,
    output_tag: str,
    model_snapshot: Path,
    model_snapshot_receipt: Path,
    dockerfile: Path,
    verify_script: Path,
    start_script: Path,
    qualification_script: Path,
    attestation_out: Path,
) -> dict[str, Any]:
    pins = _read_pins(dockerfile)
    snapshot_receipt = json.loads(model_snapshot_receipt.read_text(encoding="utf-8"))
    if snapshot_receipt.get("resolved_revision") != pins.model_revision:
        raise RuntimeError("model snapshot revision does not match Dockerfile pin")
    if snapshot_receipt.get("model_safetensors_sha256") != "sha256:" + pins.model_sha256:
        raise RuntimeError("model snapshot SHA does not match Dockerfile pin")
    if _sha_file(model_snapshot / "model.safetensors") != "sha256:" + pins.model_sha256:
        raise RuntimeError("materialized model.safetensors does not match Dockerfile pin")

    base_index = json.loads((base_oci / "index.json").read_text(encoding="utf-8"))
    base_descriptor = _find_tag(base_index, base_tag)
    base_manifest = _read_json_blob(base_oci, str(base_descriptor["digest"]))
    if base_manifest.get("mediaType") != OCI_MANIFEST:
        raise RuntimeError("base OCI manifest media type is unsupported")
    base_config = _read_json_blob(base_oci, str(base_manifest["config"]["digest"]))
    if base_config.get("architecture") != "amd64" or base_config.get("os") != "linux":
        raise RuntimeError("base OCI platform is not linux/amd64")
    base_layers = base_manifest.get("layers") or []
    base_diff_ids = base_config.get("rootfs", {}).get("diff_ids", [])
    if len(base_layers) != len(base_diff_ids):
        raise RuntimeError("base layer/diff-id cardinality mismatch")

    source_digest = pins.base_image.rsplit("@", 1)[1]
    download_receipt_path = base_oci / "download-receipt.json"
    if download_receipt_path.is_file():
        download_receipt = json.loads(download_receipt_path.read_text(encoding="utf-8"))
        if download_receipt.get("source_multiarch_digest") != source_digest:
            raise RuntimeError("verified OCI base receipt does not match Dockerfile base pin")

    baked_runtime_receipt = (
        f"base_image={pins.base_image}\n"
        f"model_revision={pins.model_revision}\n"
        f"model_safetensors_sha256={pins.model_sha256}\n"
        "runtime_dependency_verification=required_at_gpu_qualification\n"
        "bake_method=daemonless-oci-single-layer-v1\n"
    ).encode()

    _copy_layout(base_oci, output_oci)
    layer_bytes, diff_id, layer_digest, file_hashes = _build_layer(
        snapshot=model_snapshot,
        verify_script=verify_script,
        start_script=start_script,
        qualification_script=qualification_script,
        baked_receipt=baked_runtime_receipt,
    )
    actual_layer_digest = _write_blob(output_oci, layer_bytes)
    if actual_layer_digest != layer_digest:
        raise AssertionError("layer digest drift")

    config = json.loads(json.dumps(base_config))
    config.setdefault("rootfs", {}).setdefault("diff_ids", []).append(diff_id)
    runtime_config = config.setdefault("config", {})
    runtime_config["User"] = "root"
    runtime_config["Env"] = _merge_env(
        runtime_config.get("Env") or [],
        {
            "FOLYNTA_MODEL_ROOT": "/opt/folynta/models/OvisOCR2",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "HF_HUB_ENABLE_HF_TRANSFER": "0",
            "MODEL_REVISION": pins.model_revision,
        },
    )
    runtime_config["Entrypoint"] = ["/opt/folynta/start-ssh.sh"]
    runtime_config["Cmd"] = None
    exposed = dict(runtime_config.get("ExposedPorts") or {})
    exposed["22/tcp"] = {}
    exposed["8001/tcp"] = {}
    runtime_config["ExposedPorts"] = exposed
    config.setdefault("history", []).append(
        {
            "created": "1970-01-01T00:00:00Z",
            "created_by": "TAVONEL daemonless OCI bake v1",
            "comment": "pinned OvisOCR2 model and qualification runtime",
        }
    )
    config_bytes = _canonical(config)
    config_digest = _write_blob(output_oci, config_bytes)

    manifest = json.loads(json.dumps(base_manifest))
    manifest["config"] = {
        "mediaType": OCI_CONFIG,
        "digest": config_digest,
        "size": len(config_bytes),
    }
    manifest.setdefault("layers", []).append(
        {"mediaType": OCI_LAYER_GZIP, "digest": layer_digest, "size": len(layer_bytes)}
    )
    manifest_bytes = _canonical(manifest)
    manifest_digest = _write_blob(output_oci, manifest_bytes)

    index = json.loads((output_oci / "index.json").read_text(encoding="utf-8"))
    if any(
        (item.get("annotations") or {}).get("org.opencontainers.image.ref.name") == output_tag
        for item in index.get("manifests", [])
    ):
        raise RuntimeError(f"output OCI tag already exists: {output_tag}")
    index.setdefault("manifests", []).append(
        {
            "mediaType": OCI_MANIFEST,
            "digest": manifest_digest,
            "size": len(manifest_bytes),
            "platform": {"architecture": "amd64", "os": "linux"},
            "annotations": {"org.opencontainers.image.ref.name": output_tag},
        }
    )
    (output_oci / "index.json").write_bytes(_canonical(index))

    attestation = {
        "schema": "tavonel.daemonless-oci-bake-attestation.v1",
        "base_image": pins.base_image,
        "base_oci_tag": base_tag,
        "base_manifest_digest": base_descriptor["digest"],
        "base_layer_count": len(base_manifest["layers"]),
        "base_layers_preserved": [item["digest"] for item in base_manifest["layers"]],
        "dockerfile_sha256": _sha_file(dockerfile),
        "model_snapshot_receipt_sha256": _sha_file(model_snapshot_receipt),
        "model_revision": pins.model_revision,
        "model_artifact_sha256": "sha256:" + pins.model_sha256,
        "runtime_files": file_hashes,
        "new_layer_diff_id": diff_id,
        "new_layer_digest": layer_digest,
        "output_config_digest": config_digest,
        "output_manifest_digest": manifest_digest,
        "output_tag": output_tag,
        "runtime_dependency_verification": "GPU_QUALIFICATION_REQUIRED",
        "public_benchmark_inference_allowed": False,
    }
    attestation["receipt_sha256"] = canonical_sha256(attestation)
    attestation_out.parent.mkdir(parents=True, exist_ok=True)
    attestation_out.write_text(
        json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return attestation


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-oci", type=Path, required=True)
    p.add_argument("--base-tag", default="vllm-base")
    p.add_argument("--output-oci", type=Path, required=True)
    p.add_argument("--output-tag", required=True)
    p.add_argument("--model-snapshot", type=Path, required=True)
    p.add_argument("--model-snapshot-receipt", type=Path, required=True)
    p.add_argument("--dockerfile", type=Path, required=True)
    p.add_argument("--verify-script", type=Path, required=True)
    p.add_argument("--start-script", type=Path, required=True)
    p.add_argument("--qualification-script", type=Path, required=True)
    p.add_argument("--attestation-out", type=Path, required=True)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    attestation = bake(**vars(args))
    print(
        json.dumps(
            {
                "output_manifest_digest": attestation["output_manifest_digest"],
                "new_layer_digest": attestation["new_layer_digest"],
                "model_artifact_sha256": attestation["model_artifact_sha256"],
                "receipt_sha256": attestation["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
