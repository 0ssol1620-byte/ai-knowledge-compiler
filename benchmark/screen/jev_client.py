"""Jev crop-verifier client: one HTTPS call, every failure becomes an explicit state.

The call goes through ``runners.base.run_external`` (HTTPS only, host allowlist,
pinned public IP, bounded response). An unreachable verifier is recorded as OFF
with the named fallback; it is never an accept.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Callable
from typing import Any

from akc_quality.crop_verifier import VerifierRequest, VerifierResult, build_result, off_result

from benchmark.runners.base import RunnerConfig, RunnerUnavailable, run_external

MAX_CROP_BYTES = 5 * 1024 * 1024

Transport = Callable[[RunnerConfig, dict[str, Any]], dict[str, Any]]


def verify_crop(
    config: RunnerConfig,
    request: VerifierRequest,
    crop_bytes: bytes | None,
    *,
    calibrated_renderer: tuple[str, str],
    transport: Transport = run_external,
) -> VerifierResult:
    """``config.provider`` is the verifier id and ``config.model_revision`` its exact revision."""
    verifier_id, revision = config.provider, config.model_revision

    def result(raw: object) -> VerifierResult:
        return build_result(
            request,
            raw,
            calibrated_renderer=calibrated_renderer,
            verifier_id=verifier_id,
            revision=revision,
        )

    if crop_bytes is None or not request.crop_sha256:
        return VerifierResult("HOLD_MISSING_CROP", None, verifier_id, revision)
    if len(crop_bytes) > MAX_CROP_BYTES:
        raise ValueError("crop exceeds the verifier size bound")
    if not hmac.compare_digest(hashlib.sha256(crop_bytes).hexdigest(), request.crop_sha256):
        raise ValueError("crop bytes do not match crop_sha256")
    if (request.renderer_id, request.renderer_version) != calibrated_renderer:
        return result(None)  # a crop the calibration cannot apply to is not sent
    payload = {
        "region_id": request.region_id,
        "region_kind": request.region_kind,
        "candidate_text": request.candidate_text,
        "crop_sha256": request.crop_sha256,
        "crop_base64": base64.b64encode(crop_bytes).decode("ascii"),
    }
    try:
        response = transport(config, payload)
    except RunnerUnavailable:
        return off_result(verifier_id, revision)
    except ValueError:  # non-JSON body
        return result(None)
    return result(response.get("score"))
