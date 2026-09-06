#!/usr/bin/env python3
"""Seal or verify the sole outcome-blind SFIR2 frame authority."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))
import sfir2_execution as sx  # noqa: E402

SCHEMA = "tavonel.sfir2.frame_authority.v1"


def assess(acquired: dict, acquisition_path: Path) -> dict:
    if (
        acquired.get("schema") != "tavonel.sfir2.acquisition.v1"
        or acquired.get("protocol_id") != sx.PROTOCOL_ID
    ):
        raise sx.Refused("acquisition schema or protocol differs from SFIR2")
    verified = sx.reverify_recorded_bindings(acquired.get("design_bindings"))
    frozen = sx.verify_receipt(
        "protocol_freeze",
        sx.ROOT / verified["protocol_freeze"]["path"],
        verified["protocol_freeze"]["sha256"],
    )["body"]
    if (
        frozen.get("acquisition_authorized") is not True
        or frozen.get("score_exactly_once") is not True
    ):
        raise sx.Refused("protocol freeze does not authorize exactly-once acquisition and scoring")
    admitted = acquired.get("admitted")
    if not isinstance(admitted, list):
        raise sx.Refused("acquisition admitted is not a list")
    by_family: dict[str, int] = {}
    power = {endpoint: 0 for endpoint in sx.EXERCISE_REQUIREMENTS}
    sampling = {endpoint: 0 for endpoint in sx.EXERCISE_REQUIREMENTS}
    concerns: list[str] = []
    for row in admitted:
        if not isinstance(row, dict) or not isinstance(row.get("family"), str):
            raise sx.Refused("an admitted row has no family")
        by_family[row["family"]] = by_family.get(row["family"], 0) + 1
        expected = sx.exercise_eligibility(row.get("capability_exercise") or {})
        if row.get("exercise_eligibility") != expected:
            concerns.append(
                f"{row.get('lineage_id')} exercise eligibility differs from frozen flags"
            )
            continue
        for endpoint, block in expected.items():
            sampling[endpoint] += int(block["eligible"] is True)
        observations = row.get("endpoint_observations")
        if not isinstance(observations, dict) or set(observations) != set(sx.ENDPOINTS):
            raise sx.Refused(f"{row.get('lineage_id')} has no exact endpoint observation map")
        for endpoint in power:
            block = observations[endpoint]
            if not isinstance(block, dict) or type(block.get("exercised")) is not bool:
                raise sx.Refused(
                    f"{row.get('lineage_id')} has no actual exercise indicator for {endpoint}"
                )
            power[endpoint] += int(block["exercised"] is True)
    candidates = int((acquired.get("frame") or {}).get("candidates", -1))
    considered = int(acquired.get("lineages_considered", -1))
    ending = "EXHAUSTED" if candidates >= 0 and considered == candidates else "NEITHER"
    families_at_floor = sum(count >= sx.MIN_PER_FAMILY for count in by_family.values())
    if acquired.get("acquisition_state") != "ACQUIRED":
        concerns.append("the exact observation batch was not acquired")
    if ending != "EXHAUSTED":
        concerns.append("the exact frozen roster was not exhausted")
    if len(admitted) < sx.MIN_TOTAL:
        concerns.append(f"total {len(admitted)} is below {sx.MIN_TOTAL}")
    if families_at_floor < sx.MIN_FAMILIES:
        concerns.append(f"only {families_at_floor} families meet the {sx.MIN_PER_FAMILY} floor")
    for endpoint, count in power.items():
        if count < sx.MIN_EXERCISING:
            concerns.append(
                f"{endpoint} has {count} actually exercising rows; need {sx.MIN_EXERCISING}"
            )
    return {
        "schema": SCHEMA,
        "protocol_id": sx.PROTOCOL_ID,
        "authority": {
            "path": sx.relative(sx.FRAME_AUTHORITY),
            "single_immutable_authority": True,
            "newest_wins": False,
        },
        "acquisition": sx.relative(acquisition_path),
        "acquisition_sha256": sx.sha_file(acquisition_path),
        "design_bindings": verified,
        "ending": ending,
        "counts": {
            "total": len(admitted),
            "by_family": dict(sorted(by_family.items())),
            "families_at_floor": families_at_floor,
        },
        "exercise_power": power,
        "predeclared_sampling_strata": sampling,
        "exercise_definition": {
            "source": "actual endpoint_observations[*].exercised",
            "score_outcomes_inspected": False,
            "violation_counts_inspected": False,
        },
        "thresholds": {
            "total": sx.MIN_TOTAL,
            "families": sx.MIN_FAMILIES,
            "per_family": sx.MIN_PER_FAMILY,
            "E5_E6_E9_exercising": sx.MIN_EXERCISING,
        },
        "concerns": concerns,
        "state": "SCORABLE" if not concerns else "NOT_SCORABLE",
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def seal(acquisition: Path, authority: Path = sx.FRAME_AUTHORITY) -> dict:
    if authority.resolve() != sx.FRAME_AUTHORITY.resolve():
        raise sx.Refused("SFIR2 frame has one fixed authority path")
    body = assess(sx.read_json(acquisition), acquisition)
    sx.exclusive_json(authority, body)
    return body


def verify(path: Path = sx.FRAME_AUTHORITY) -> dict:
    body = sx.verify_fixed_authority(path, sx.FRAME_AUTHORITY, SCHEMA)
    if body.get("state") != "SCORABLE":
        raise sx.Refused(f"SFIR2 frame authority is {body.get('state')}, not SCORABLE")
    if sx.reverify_recorded_bindings(body.get("design_bindings")) != body.get("design_bindings"):
        raise sx.Refused("frame authority bindings are not canonical")
    acquisition = sx.ROOT / body["acquisition"]
    if not acquisition.is_file() or sx.sha_file(acquisition) != body.get("acquisition_sha256"):
        raise sx.Refused("frame acquisition binding moved")
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acquisition", type=Path, default=sx.ACQUISITION)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    try:
        body = verify(args.verify) if args.verify else seal(args.acquisition)
        print(
            json.dumps(
                {
                    "state": body["state"],
                    "authority": sx.relative(sx.FRAME_AUTHORITY),
                    "concerns": body.get("concerns", []),
                },
                indent=2,
            )
        )
        return 0 if body["state"] == "SCORABLE" else 4
    except sx.Refused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=2), file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
