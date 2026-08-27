#!/usr/bin/env python3
"""Seal/verify the one SFIR1 acceptance authority from an exact PASS score."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))
import score_sfir1  # noqa: E402
import sfir1_execution as sx  # noqa: E402

SCHEMA = "tavonel.sfir1.acceptance_authority.v1"


def seal(
    score_authority: Path, score_sha256: str, authority: Path = sx.ACCEPTANCE_AUTHORITY
) -> dict:
    if authority.resolve() != sx.ACCEPTANCE_AUTHORITY.resolve():
        raise sx.Refused("SFIR1 acceptance has one fixed authority path")
    if score_authority.resolve() != sx.SCORE_AUTHORITY.resolve():
        raise sx.Refused("acceptance requires the fixed SFIR1 score authority, not an alternate")
    if not score_authority.is_file() or sx.sha_file(score_authority) != score_sha256:
        raise sx.Refused("acceptance score path or digest is not the exact supplied authority")
    score = sx.verify_fixed_authority(score_authority, sx.SCORE_AUTHORITY, score_sfir1.SCHEMA)
    if score.get("state") != "SCORED" or score.get("verdict") != "PASS":
        raise sx.Refused(
            f"SFIR1 score is {score.get('state')}/{score.get('verdict')}, not SCORED/PASS"
        )
    # Only a terminal PASS needs the expensive full-chain revalidation.  This
    # preserves an exact diagnostic for terminal FAIL/refusal authorities while
    # still refusing acceptance if any frozen execution byte drifted.
    score = score_sfir1.verify(score_authority)
    endpoints = score.get("endpoints")
    if not isinstance(endpoints, dict) or set(endpoints) != set(sx.ENDPOINTS):
        raise sx.Refused("score endpoint domain is not the exact declared SFIR1 domain")
    if any(endpoints[name].get("verdict") != "MET" for name in sx.PRIMARY_ENDPOINTS):
        raise sx.Refused("not every SFIR1 primary endpoint is MET")
    if endpoints[sx.VETO_ENDPOINT].get("verdict") != "VETO_CLEAR_NO_POSITIVE_CREDIT":
        raise sx.Refused("SFIR1 safety veto is not clear")
    body = {
        "schema": SCHEMA,
        "protocol_id": sx.PROTOCOL_ID,
        "authority": {
            "path": sx.relative(authority),
            "single_immutable_authority": True,
            "newest_wins": False,
        },
        "score_authority": sx.relative(score_authority),
        "score_authority_sha256": score_sha256,
        "frame_authority": score["frame_authority"],
        "frame_authority_sha256": score["frame_authority_sha256"],
        "acquisition": score["acquisition"],
        "acquisition_sha256": score["acquisition_sha256"],
        "state": "ACCEPTED",
        "verdict": "PASS",
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    sx.exclusive_json(authority, body)
    return body


def verify(path: Path = sx.ACCEPTANCE_AUTHORITY) -> dict:
    body = sx.verify_fixed_authority(path, sx.ACCEPTANCE_AUTHORITY, SCHEMA)
    if body.get("state") != "ACCEPTED" or body.get("verdict") != "PASS":
        raise sx.Refused("SFIR1 acceptance authority is not ACCEPTED/PASS")
    score_path = sx.ROOT / body["score_authority"]
    if not score_path.is_file() or sx.sha_file(score_path) != body.get("score_authority_sha256"):
        raise sx.Refused("accepted score authority moved")
    score = score_sfir1.verify(score_path)
    if (
        score.get("state") != "SCORED"
        or score.get("verdict") != "PASS"
        or body.get("frame_authority") != score.get("frame_authority")
        or body.get("frame_authority_sha256") != score.get("frame_authority_sha256")
        or body.get("acquisition") != score.get("acquisition")
        or body.get("acquisition_sha256") != score.get("acquisition_sha256")
    ):
        raise sx.Refused("acceptance authority no longer resolves an exact PASS chain")
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--score-authority", type=Path)
    parser.add_argument("--score-authority-sha256")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.verify:
            body = verify(args.verify)
        elif args.score_authority and args.score_authority_sha256:
            body = seal(args.score_authority, args.score_authority_sha256)
        else:
            raise sx.Refused("explicit score authority path+sha256 or --verify is required")
        print(
            json.dumps(
                {"state": body["state"], "authority": sx.relative(sx.ACCEPTANCE_AUTHORITY)},
                indent=2,
            )
        )
        return 0
    except sx.Refused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=2), file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
