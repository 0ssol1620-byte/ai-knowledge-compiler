"""Run explicitly (workers/ is not collected):
PYTHONPATH=packages/quality/src py -3.13 -m pytest workers/gpu-verifier/test_handler.py
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import importlib
import json
import runpy
import sys
import types
import typing
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import handler

REV = "1" * 40
RENDERER = ("pdfium", "1.0")


def _payload(crop: bytes = b"crop", **kw: object) -> dict[str, typing.Any]:
    p: dict[str, typing.Any] = {
        "crop_b64": base64.b64encode(crop).decode(),
        "candidate_text": "x",
        "renderer_id": "pdfium",
        "renderer_version": "1.0",
    }
    p.update(kw)
    return p


def _ok(crop: bytes, text: str) -> float:
    return 0.9


def _run(payload: dict[str, typing.Any], scorer: handler.Scorer = _ok) -> dict[str, typing.Any]:
    return handler.handle(payload, scorer, revision=REV, calibrated_renderer=RENDERER)


def test_scored() -> None:
    out = _run(_payload())
    assert out["state"] == "SCORED" and out["score"] == 0.9


def test_oversize_crop_refused() -> None:
    with pytest.raises(handler.RefusedInput):
        _run(_payload(b"x" * (handler.MAX_CROP_BYTES + 1)))


def test_holds() -> None:
    assert _run(_payload(crop_b64=""))["state"] == "HOLD_MISSING_CROP"
    assert _run(_payload(renderer_version="2"))["state"] == "HOLD_RENDERER_MISMATCH"
    assert _run(_payload(), lambda c, t: float("nan"))["state"] == "HOLD_INVALID_OUTPUT"
    assert _run(_payload(), lambda c, t: True)["state"] == "HOLD_INVALID_OUTPUT"


def test_scorer_failure_is_operational_not_a_hold() -> None:
    def boom(c: bytes, t: str) -> float:
        raise MemoryError("CUDA out of memory")

    with pytest.raises(handler.ScorerFailed, match="MemoryError"):
        _run(_payload(), boom)


def test_non_object_input_and_non_string_crop_refused() -> None:
    with pytest.raises(handler.RefusedInput, match="object"):
        _run(None)  # type: ignore[arg-type]
    with pytest.raises(handler.RefusedInput, match="string"):
        _run(_payload(crop_b64=5))


def _manifest(tmp: Path, sha: str) -> Path:
    (tmp / "w.bin").write_bytes(b"weights")
    m = tmp / "manifest.json"
    m.write_text(json.dumps({"files": {"w.bin": sha}}))
    return m


def _pin(m: Path) -> str:
    return hashlib.sha256(m.read_bytes()).hexdigest()


def test_manifest_ok_and_mismatch(tmp_path: Path) -> None:
    good = _manifest(tmp_path, hashlib.sha256(b"weights").hexdigest())
    handler.verify_weights(good, tmp_path, _pin(good))
    bad = _manifest(tmp_path, "0" * 64)
    with pytest.raises(RuntimeError, match="weight sha256 mismatch"):
        handler.verify_weights(bad, tmp_path, _pin(bad))


def test_regenerated_manifest_fails_pinned_digest(tmp_path: Path) -> None:
    good = _manifest(tmp_path, hashlib.sha256(b"weights").hexdigest())
    pin = _pin(good)
    (tmp_path / "w.bin").write_bytes(b"EVIL")  # swap weights and rebuild the manifest
    good.write_text(json.dumps({"files": {"w.bin": hashlib.sha256(b"EVIL").hexdigest()}}))
    with pytest.raises(RuntimeError, match="manifest sha256 mismatch"):
        handler.verify_weights(good, tmp_path, pin)


def test_unlisted_weight_file_refused(tmp_path: Path) -> None:
    good = _manifest(tmp_path, hashlib.sha256(b"weights").hexdigest())
    (tmp_path / "extra.safetensors").write_bytes(b"x")
    with pytest.raises(RuntimeError, match="not in manifest"):
        handler.verify_weights(good, tmp_path, _pin(good))


def _start_env(
    tmp: Path, monkeypatch: pytest.MonkeyPatch, manifest: Path, pin: str, revision: str = REV
) -> None:
    adapter = tmp.with_name(tmp.name + "_adapter")
    adapter.mkdir(exist_ok=True)
    (adapter / "stub_adapter.py").write_text("def score(crop, text):\n    return 0.5\n")
    monkeypatch.syspath_prepend(str(adapter))
    monkeypatch.delitem(sys.modules, "stub_adapter", raising=False)
    for key, value in {
        "MODEL_REVISION": revision,
        "WEIGHTS_DIR": str(tmp),
        "WEIGHT_MANIFEST": str(manifest),
        "WEIGHT_MANIFEST_SHA256": pin,
        "CALIBRATED_RENDERER_ID": "pdfium",
        "CALIBRATED_RENDERER_VERSION": "1.0",
        "MODEL_ADAPTER_MODULE": "stub_adapter",
        "REQUIRE_CALLBACK_AUTH": "true",
        "CALLBACK_HMAC_SECRET": "test-not-a-secret",
    }.items():
        monkeypatch.setenv(key, value)


def _fake_runpod(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    started: list[object] = []
    fake = types.SimpleNamespace(serverless=types.SimpleNamespace(start=started.append))
    monkeypatch.setitem(sys.modules, "runpod", fake)
    return started


def test_manifest_mismatch_refuses_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    m = _manifest(tmp_path, "0" * 64)
    started = _fake_runpod(monkeypatch)
    _start_env(tmp_path, monkeypatch, m, "f" * 64)  # pin does not match the manifest
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(handler.__file__, run_name="__main__")
    assert exc.value.code == 1
    assert "sha256 mismatch" in capsys.readouterr().err
    assert not started


def test_valid_manifest_starts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = _manifest(tmp_path, hashlib.sha256(b"weights").hexdigest())
    started = _fake_runpod(monkeypatch)
    _start_env(tmp_path, monkeypatch, m, _pin(m))
    handler.main()
    assert len(started) == 1
    serve = started[0]["handler"]  # type: ignore[index]
    ok = serve({"input": _payload()})
    assert ok["state"] == "SCORED"


def test_start_refused_without_callback_auth_or_bad_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = _manifest(tmp_path, hashlib.sha256(b"weights").hexdigest())
    _fake_runpod(monkeypatch)
    _start_env(tmp_path, monkeypatch, m, _pin(m), revision="")
    with pytest.raises(RuntimeError, match="MODEL_REVISION"):
        handler.main()
    monkeypatch.setenv("MODEL_REVISION", REV)
    monkeypatch.delenv("CALLBACK_HMAC_SECRET")
    with pytest.raises(RuntimeError, match="CALLBACK"):
        handler.main()


def test_serve_one_reports_scorer_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    m = _manifest(tmp_path, hashlib.sha256(b"weights").hexdigest())
    started = _fake_runpod(monkeypatch)
    _start_env(tmp_path, monkeypatch, m, _pin(m))
    (tmp_path.with_name(tmp_path.name + "_adapter") / "stub_adapter.py").write_text(
        "def score(c, t):\n    raise MemoryError('oom')\n"
    )
    handler.main()
    out = started[0]["handler"]({"input": _payload()})  # type: ignore[index]
    assert out == {"error": "scorer_failed"}
    assert "MemoryError" in capsys.readouterr().err


def test_states_match_contract() -> None:
    cv = importlib.import_module("akc_quality.crop_verifier")
    states = set(typing.get_args(cv.VerifierState))
    ours = {"SCORED", "HOLD_MISSING_CROP", "HOLD_RENDERER_MISMATCH", "HOLD_INVALID_OUTPUT"}
    assert ours <= states
    fields = {f.name for f in dataclasses.fields(cv.VerifierResult)}
    assert set(_run(_payload())) - {"crop_sha256"} == fields
    assert set(_run(_payload(crop_b64=""))) == fields
