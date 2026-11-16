"""Jev crop-verifier worker: bounded input, no network, weights checked at start.

The verifier receives crops only (rendering lives in the parser image). Output
states mirror akc_quality.crop_verifier.VerifierResult; the image carries no
akc_quality, so test_handler.py pins the two together.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import importlib
import json
import math
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

VERIFIER_ID = "minicpm-ocr-jev"
MAX_CROP_BYTES = 4 * 1024 * 1024
MAX_TEXT_CHARS = 20_000
HEX64 = frozenset("0123456789abcdef")

Scorer = Callable[[bytes, str], object]


class RefusedInput(ValueError):
    """The request is outside the bounds; nothing was scored."""


def verify_weights(manifest_path: Path, weights_dir: Path) -> None:
    """Every manifest entry must exist under weights_dir with the exact sha256."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, dict) or not files:
        raise RuntimeError("weight manifest has no files")
    root = weights_dir.resolve()
    for name, expected in files.items():
        path = (root / name).resolve()
        if root not in path.parents or not path.is_file():
            raise RuntimeError(f"weight file missing or outside weights dir: {name}")
        if not (isinstance(expected, str) and len(expected) == 64 and set(expected) <= HEX64):
            raise RuntimeError(f"manifest sha256 malformed: {name}")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise RuntimeError(f"weight sha256 mismatch: {name}")


def _hold(state: str, revision: str) -> dict[str, Any]:
    return {
        "state": state,
        "score": None,
        "verifier_id": VERIFIER_ID,
        "revision": revision,
        "fallback": None,
    }


def handle(
    payload: dict[str, Any],
    scorer: Scorer,
    *,
    revision: str,
    calibrated_renderer: tuple[str, str],
) -> dict[str, Any]:
    text = payload.get("candidate_text")
    if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
        raise RefusedInput("candidate_text missing or too long")
    encoded = payload.get("crop_b64")
    if encoded in (None, ""):
        return _hold("HOLD_MISSING_CROP", revision)
    if not isinstance(encoded, str) or len(encoded) > MAX_CROP_BYTES * 4 // 3 + 4:
        raise RefusedInput("crop too large")
    try:
        crop = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RefusedInput("crop is not base64") from exc
    if not crop or len(crop) > MAX_CROP_BYTES:
        raise RefusedInput("crop empty or too large")
    if (payload.get("renderer_id"), payload.get("renderer_version")) != calibrated_renderer:
        return _hold("HOLD_RENDERER_MISMATCH", revision)
    try:
        raw = scorer(crop, text)
    except Exception:  # a scorer failure is a HOLD, never an accept
        return _hold("HOLD_INVALID_OUTPUT", revision)
    if (
        isinstance(raw, bool)
        or not isinstance(raw, (int, float))
        or not math.isfinite(raw)
        or not 0 <= raw <= 1
    ):
        return _hold("HOLD_INVALID_OUTPUT", revision)
    return {
        "state": "SCORED",
        "score": float(raw),
        "verifier_id": VERIFIER_ID,
        "revision": revision,
        "fallback": None,
        "crop_sha256": hashlib.sha256(crop).hexdigest(),
    }


def main() -> None:
    revision = os.environ["MODEL_REVISION"]
    verify_weights(Path(os.environ["WEIGHT_MANIFEST"]), Path(os.environ["WEIGHTS_DIR"]))
    renderer = (os.environ["CALIBRATED_RENDERER_ID"], os.environ["CALIBRATED_RENDERER_VERSION"])
    scorer: Scorer = importlib.import_module(os.environ["MODEL_ADAPTER_MODULE"]).score

    def serve_one(event: dict[str, Any]) -> dict[str, Any]:
        try:
            return handle(
                event.get("input") or {}, scorer, revision=revision, calibrated_renderer=renderer
            )
        except RefusedInput as exc:
            return {"error": str(exc)}

    import runpod  # type: ignore[import-not-found]  # present in the image only

    runpod.serverless.start({"handler": serve_one})


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # start-up failure must exit non-zero, visibly
        print(f"jev verifier refused to start: {exc}", file=sys.stderr)
        sys.exit(1)
