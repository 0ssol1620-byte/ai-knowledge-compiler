"""Bootstrap bundle packaging tests (contract 6.4, masterplan 37)."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from pathlib import Path

import pytest
from arena.constants import CAMPAIGN_ID, NAMESPACE_ROOT
from arena.worker.bundle import (
    BOOTSTRAP_NAME,
    BUNDLE_MANIFEST_NAME,
    BundleError,
    build_bundle,
    read_bundle,
    read_bundle_manifest,
    verify_bundle,
)
from arena.worker.util import sha256_label

MODEL_KEY = "paddleocr_vl_1_6"


def _retar(source: Path, target: Path, *, replace: dict[str, bytes]) -> None:
    """Rebuild an archive with some member payloads swapped out."""
    contents = read_bundle(source)
    contents.update(replace)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name in sorted(contents):
            data = contents[name]
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    target.write_bytes(gzip.compress(buffer.getvalue(), mtime=0))


def test_build_bundle_is_deterministic_and_complete(tmp_path: Path) -> None:
    first = tmp_path / "bundle-a.tar.gz"
    second = tmp_path / "bundle-b.tar.gz"
    sha_a = build_bundle(MODEL_KEY, first)
    sha_b = build_bundle(MODEL_KEY, second)

    assert sha_a.startswith("sha256:")
    assert sha_a == sha_b, "the bundle hash feeds inference_job_id and must be stable"
    assert sha_a == sha_label_of(first)

    contents = read_bundle(first)
    assert "arena/worker/server.py" in contents
    assert "arena/worker/adapter_api.py" in contents
    assert "arena/constants.py" in contents
    assert BOOTSTRAP_NAME in contents
    assert BUNDLE_MANIFEST_NAME in contents
    assert not any(".pyc" in name or "__pycache__" in name for name in contents)


def sha_label_of(path: Path) -> str:
    return sha256_label(path.read_bytes())


def test_manifest_lists_every_member_with_its_hash(tmp_path: Path) -> None:
    out = tmp_path / "bundle.tar.gz"
    build_bundle(MODEL_KEY, out)
    manifest = read_bundle_manifest(out)
    contents = read_bundle(out)

    assert manifest["campaign_id"] == CAMPAIGN_ID
    assert manifest["model_key"] == MODEL_KEY
    assert manifest["file_count"] == len(manifest["files"])
    listed = {entry["path"] for entry in manifest["files"]}
    assert listed == set(contents) - {BUNDLE_MANIFEST_NAME}
    for entry in manifest["files"]:
        assert entry["sha256"] == sha256_label(contents[entry["path"]])
        assert entry["size"] == len(contents[entry["path"]])

    verification = verify_bundle(out)
    assert verification.ok
    assert verification.problems == ()
    assert verification.file_count == manifest["file_count"]


def test_sidecar_receipt_records_the_runtime_image_digest(tmp_path: Path) -> None:
    out = tmp_path / "bundle.tar.gz"
    bundle_sha = build_bundle(MODEL_KEY, out)
    sidecar = json.loads(
        (tmp_path / "bundle.tar.gz.manifest.json").read_text(encoding="utf-8")
    )
    assert sidecar["runtime_bundle_sha256"] == bundle_sha
    assert sidecar["runtime_image_digest"] == f"bootstrap:{bundle_sha}"
    assert sidecar["model_key"] == MODEL_KEY
    assert sidecar["bundle_bytes"] == out.stat().st_size


def test_bootstrap_script_verifies_then_delegates_then_execs(tmp_path: Path) -> None:
    out = tmp_path / "bundle.tar.gz"
    build_bundle(MODEL_KEY, out)
    script = read_bundle(out)[BOOTSTRAP_NAME].decode("utf-8")
    assert script.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in script
    assert BUNDLE_MANIFEST_NAME in script
    assert "bundle verification FAILED" in script
    # The delegation target is $ARENA_RUNTIME_DIR/bootstrap.sh via the symlink
    # (ARENA_CONTRACT 11.3(3)); tests/worker/test_bootstrap_handoff.py checks
    # the symlink, the exports and the delegation/FATAL handling in detail.
    assert 'RUNTIME_BOOTSTRAP="$ARENA_RUNTIME_DIR/bootstrap.sh"' in script
    assert "$BUNDLE_ROOT/bootstrap-receipt.txt" in script
    assert "pip freeze" in script
    assert "pip install -U" not in script
    assert 'bash "$RUNTIME_BOOTSTRAP"' in script
    assert script.rstrip().endswith('exec "$PYTHON_BIN" -m arena.worker.server')


def test_tampered_member_is_detected(tmp_path: Path) -> None:
    original = tmp_path / "bundle.tar.gz"
    tampered = tmp_path / "tampered.tar.gz"
    build_bundle(MODEL_KEY, original)
    _retar(
        original,
        tampered,
        replace={"arena/worker/server.py": b"# replaced by an attacker\n"},
    )

    verification = verify_bundle(tampered)
    assert not verification.ok
    assert "hash mismatch: arena/worker/server.py" in verification.problems


def test_added_member_is_detected(tmp_path: Path) -> None:
    original = tmp_path / "bundle.tar.gz"
    tampered = tmp_path / "tampered.tar.gz"
    build_bundle(MODEL_KEY, original)
    _retar(original, tampered, replace={"arena/worker/backdoor.py": b"import os\n"})

    verification = verify_bundle(tampered)
    assert not verification.ok
    assert any("backdoor.py" in problem for problem in verification.problems)


def test_removed_member_is_detected(tmp_path: Path) -> None:
    original = tmp_path / "bundle.tar.gz"
    tampered = tmp_path / "tampered.tar.gz"
    build_bundle(MODEL_KEY, original)
    contents = read_bundle(original)
    del contents["arena/worker/heartbeat.py"]
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name in sorted(contents):
            info = tarfile.TarInfo(name)
            info.size = len(contents[name])
            info.mtime = 0
            tar.addfile(info, io.BytesIO(contents[name]))
    tampered.write_bytes(gzip.compress(buffer.getvalue(), mtime=0))

    verification = verify_bundle(tampered)
    assert not verification.ok
    assert any("missing from archive" in problem for problem in verification.problems)


def test_unknown_model_key_is_refused(tmp_path: Path) -> None:
    with pytest.raises(BundleError, match="unknown model_key"):
        build_bundle("not_a_model", tmp_path / "bundle.tar.gz")


def test_missing_namespace_is_refused(tmp_path: Path) -> None:
    with pytest.raises(BundleError, match="arena package not found"):
        build_bundle(MODEL_KEY, tmp_path / "bundle.tar.gz", namespace_root=tmp_path / "nowhere")


def test_unsafe_member_path_is_refused(tmp_path: Path) -> None:
    hostile = tmp_path / "hostile.tar.gz"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        data = b"payload"
        info = tarfile.TarInfo("../escaped.py")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    hostile.write_bytes(gzip.compress(buffer.getvalue(), mtime=0))

    with pytest.raises(BundleError, match="unsafe member path"):
        read_bundle(hostile)


def test_cli_builds_and_verifies(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from arena.worker.bundle import main

    out = tmp_path / "cli-bundle.tar.gz"
    code = main(
        [
            "--model",
            MODEL_KEY,
            "--out",
            str(out),
            "--namespace-root",
            str(NAMESPACE_ROOT),
            "--verify",
        ]
    )
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["model_key"] == MODEL_KEY
    assert report["verified"] is True
    assert report["problems"] == []
    assert report["runtime_image_digest"] == f"bootstrap:{report['runtime_bundle_sha256']}"
    assert out.is_file()
