"""Run explicitly (workers/ is not collected):
PYTHONPATH=packages/quality/src py -3.13 -m pytest workers/gpu-verifier/test_handler.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import runpy
import sys
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

    def boom(c: bytes, t: str) -> float:
        raise RuntimeError

    assert _run(_payload(), boom)["state"] == "HOLD_INVALID_OUTPUT"


def _manifest(tmp: Path, sha: str) -> Path:
    (tmp / "w.bin").write_bytes(b"weights")
    m = tmp / "manifest.json"
    m.write_text(json.dumps({"files": {"w.bin": sha}}))
    return m


def test_manifest_ok_and_mismatch(tmp_path: Path) -> None:
    handler.verify_weights(_manifest(tmp_path, hashlib.sha256(b"weights").hexdigest()), tmp_path)
    with pytest.raises(RuntimeError, match="mismatch"):
        handler.verify_weights(_manifest(tmp_path, "0" * 64), tmp_path)


def test_manifest_mismatch_refuses_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = _manifest(tmp_path, "0" * 64)
    monkeypatch.setenv("MODEL_REVISION", REV)
    monkeypatch.setenv("WEIGHTS_DIR", str(tmp_path))
    monkeypatch.setenv("WEIGHT_MANIFEST", str(m))
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(handler.__file__, run_name="__main__")
    assert exc.value.code == 1


def test_states_match_contract() -> None:
    cv = pytest.importorskip("akc_quality.crop_verifier")
    states = set(typing.get_args(cv.VerifierState))
    ours = {"SCORED", "HOLD_MISSING_CROP", "HOLD_RENDERER_MISMATCH", "HOLD_INVALID_OUTPUT"}
    assert ours <= states
    assert set(_run(_payload())) >= {"state", "score", "verifier_id", "revision", "fallback"}
