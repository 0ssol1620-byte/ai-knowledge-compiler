#!/usr/bin/env python3
"""Spend SFIR3's single score attempt against its exact SCORABLE frame."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))
import sfir3_execution as sx  # noqa: E402
import verify_sfir3_frame as frame  # noqa: E402

SCHEMA = "tavonel.sfir3.score_authority.v1"


def _score(acquired: dict) -> dict:
    admitted = acquired.get("admitted")
    if not isinstance(admitted, list):
        raise sx.Refused("malformed acquisition: admitted is not a list")
    endpoint_rows: dict[str, dict] = {}
    for endpoint in sx.ENDPOINTS:
        exercising = violations = 0
        stages: set[str] = set()
        for row in admitted:
            block = (
                (row.get("endpoint_observations") or {}).get(endpoint)
                if isinstance(row, dict)
                else None
            )
            if not isinstance(block, dict) or type(block.get("exercised")) is not bool:
                raise sx.Refused(f"malformed acquisition: missing {endpoint} observation")
            exercising += int(block["exercised"] is True)
            value = block.get("violations")
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise sx.Refused(f"malformed acquisition: invalid violation count for {endpoint}")
            violations += value
            checked = block.get("stages_checked") or []
            if not isinstance(checked, list) or any(not isinstance(item, str) for item in checked):
                raise sx.Refused(f"malformed acquisition: invalid stages for {endpoint}")
            stages.update(checked)
        if endpoint == sx.VETO_ENDPOINT:
            verdict = (
                "VETO_CLEAR_NO_POSITIVE_CREDIT"
                if violations == 0 and {"post_execution", "pre_activation"} <= stages
                else "FAILED"
            )
        else:
            verdict = (
                "MET"
                if violations == 0 and exercising > 0
                else ("FAILED" if violations else "SKIPPED_NEVER_EXERCISED")
            )
        if endpoint in sx.EXERCISE_REQUIREMENTS and exercising < sx.MIN_EXERCISING:
            verdict = "FAILED"
        endpoint_rows[endpoint] = {
            "verdict": verdict,
            "pairs_exercising": exercising,
            "violations": violations,
            "stages_checked": sorted(stages),
            "required_exercising": sx.MIN_EXERCISING
            if endpoint in sx.EXERCISE_REQUIREMENTS
            else None,
            "underpowered": endpoint in sx.EXERCISE_REQUIREMENTS and exercising < sx.MIN_EXERCISING,
        }
    failed = [name for name in sx.PRIMARY_ENDPOINTS if endpoint_rows[name]["verdict"] != "MET"]
    veto_failed = endpoint_rows[sx.VETO_ENDPOINT]["verdict"] != "VETO_CLEAR_NO_POSITIVE_CREDIT"
    return {
        "endpoints": endpoint_rows,
        "verdict": "PASS" if not failed and not veto_failed else "FAIL",
        "failed": failed,
        "safety_veto_failed": veto_failed,
    }


def score(frame_authority: Path, frame_sha256: str, authority: Path = sx.SCORE_AUTHORITY) -> dict:
    if authority.resolve() != sx.SCORE_AUTHORITY.resolve():
        raise sx.Refused("SFIR3 score has one fixed authority path")
    if (
        frame_authority.resolve() != sx.FRAME_AUTHORITY.resolve()
        or not frame_authority.is_file()
        or sx.sha_file(frame_authority) != frame_sha256
    ):
        raise sx.Refused("scorer requires the exact fixed SFIR3 frame path and sha256")
    held = frame.verify(frame_authority)
    attempt = {
        "schema": SCHEMA,
        "protocol_id": sx.PROTOCOL_ID,
        "authority": {
            "path": sx.relative(authority),
            "single_immutable_authority": True,
            "exactly_once": True,
        },
        "frame_authority": sx.relative(frame_authority),
        "frame_authority_sha256": frame_sha256,
        "acquisition": held["acquisition"],
        "acquisition_sha256": held["acquisition_sha256"],
        "state": "SCORING_ATTEMPT_RESERVED",
        "verdict": "REFUSED",
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    sx.exclusive_json(authority, attempt)
    try:
        acquisition = sx.ROOT / held["acquisition"]
        if not acquisition.is_file() or sx.sha_file(acquisition) != held["acquisition_sha256"]:
            raise sx.Refused("acquisition moved after frame authority")
        attempt.update(_score(sx.read_json(acquisition)))
        attempt["state"] = "SCORED"
    except Exception as error:
        attempt["state"] = "MALFORMED_PARTIAL_REFUSED"
        attempt["refusal"] = f"{type(error).__name__}: {error}"
    terminal = authority.with_name(f".{authority.name}.terminal-{os.getpid()}")
    sx.exclusive_json(terminal, attempt)
    os.replace(terminal, authority)
    return attempt


def verify(path: Path = sx.SCORE_AUTHORITY) -> dict:
    body = sx.verify_fixed_authority(path, sx.SCORE_AUTHORITY, SCHEMA)
    frame_path = sx.ROOT / str(body.get("frame_authority") or "")
    if (
        frame_path.resolve() != sx.FRAME_AUTHORITY.resolve()
        or not frame_path.is_file()
        or sx.sha_file(frame_path) != body.get("frame_authority_sha256")
    ):
        raise sx.Refused("score authority frame binding moved")
    held = frame.verify(frame_path)
    if body.get("acquisition") != held.get("acquisition") or body.get(
        "acquisition_sha256"
    ) != held.get("acquisition_sha256"):
        raise sx.Refused("score acquisition chain differs from its frame")
    if body.get("state") == "SCORED":
        acquisition = sx.ROOT / held["acquisition"]
        expected = _score(sx.read_json(acquisition))
        if any(body.get(key) != expected[key] for key in expected):
            raise sx.Refused("score authority does not reconstruct from the exact acquisition")
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame-authority", type=Path, required=True)
    parser.add_argument("--frame-authority-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        body = score(args.frame_authority, args.frame_authority_sha256)
        print(
            json.dumps(
                {
                    "state": body["state"],
                    "verdict": body["verdict"],
                    "authority": sx.relative(sx.SCORE_AUTHORITY),
                },
                indent=2,
            )
        )
        return 0 if body.get("verdict") == "PASS" else 4
    except sx.Refused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=2), file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
