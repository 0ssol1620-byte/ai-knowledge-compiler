#!/usr/bin/env python3
"""Seal/verify SFIR4's sole acceptance authority from an exact PASS score."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))
import score_sfir4  # noqa: E402
import sfir4_execution as sx  # noqa: E402

SCHEMA = "tavonel.sfir4.acceptance_authority.v1"


def seal(
    score_authority: Path, score_sha256: str, authority: Path = sx.ACCEPTANCE_AUTHORITY
) -> dict:
    if (
        authority.resolve() != sx.ACCEPTANCE_AUTHORITY.resolve()
        or score_authority.resolve() != sx.SCORE_AUTHORITY.resolve()
    ):
        raise sx.Refused("SFIR4 acceptance requires both fixed authority paths")
    if not score_authority.is_file() or sx.sha_file(score_authority) != score_sha256:
        raise sx.Refused("acceptance score path or digest is not exact")
    held = sx.verify_fixed_authority(score_authority, sx.SCORE_AUTHORITY, score_sfir4.SCHEMA)
    if held.get("state") != "SCORED" or held.get("verdict") != "PASS":
        raise sx.Refused(
            f"SFIR4 score is {held.get('state')}/{held.get('verdict')}, not SCORED/PASS"
        )
    score = score_sfir4.verify(score_authority)
    endpoints = score.get("endpoints")
    if not isinstance(endpoints, dict) or set(endpoints) != set(sx.ENDPOINTS):
        raise sx.Refused("score endpoint domain is not the exact SFIR4 domain")
    if any(endpoints[name].get("verdict") != "MET" for name in sx.PRIMARY_ENDPOINTS):
        raise sx.Refused("not every SFIR4 primary endpoint is MET")
    if endpoints[sx.VETO_ENDPOINT].get("verdict") != "VETO_CLEAR_NO_POSITIVE_CREDIT":
        raise sx.Refused("SFIR4 safety veto is not clear")
    body = {
        "schema": SCHEMA,
        "protocol_id": sx.PROTOCOL_ID,
        "authority": {
            "path": sx.relative(authority),
            "single_immutable_authority": True,
            "exactly_once": True,
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
        raise sx.Refused("SFIR4 acceptance is not ACCEPTED/PASS")
    score_path = sx.ROOT / body["score_authority"]
    if not score_path.is_file() or sx.sha_file(score_path) != body.get("score_authority_sha256"):
        raise sx.Refused("accepted score authority moved")
    score = score_sfir4.verify(score_path)
    if (
        score.get("state") != "SCORED"
        or score.get("verdict") != "PASS"
        or any(
            body.get(key) != score.get(key)
            for key in (
                "frame_authority",
                "frame_authority_sha256",
                "acquisition",
                "acquisition_sha256",
            )
        )
    ):
        raise sx.Refused("acceptance no longer resolves the exact PASS chain")
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
