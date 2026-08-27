#!/usr/bin/env python3
"""Seal the sole SFIR1 frame authority without inspecting score outcomes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))
import sfir1_execution as sx  # noqa: E402

SCHEMA = "tavonel.sfir1.frame_authority.v1"


def assess(acquired: dict, acquisition_path: Path) -> dict:
    verified_bindings = sx.reverify_recorded_bindings(acquired.get("design_bindings"))
    frozen = sx.verify_receipt(
        "protocol_freeze",
        sx.ROOT / verified_bindings["protocol_freeze"]["path"],
        verified_bindings["protocol_freeze"]["sha256"],
    )["body"]
    if frozen.get("acquisition_authorized") is not True:
        raise sx.Refused("protocol freeze does not authorize acquisition")
    if frozen.get("score_exactly_once") is not True:
        raise sx.Refused("protocol freeze does not require exactly-once scoring")
    admitted = acquired.get("admitted")
    if not isinstance(admitted, list):
        raise sx.Refused("acquisition admitted is not a list")
    by_family: dict[str, int] = {}
    power = {endpoint: 0 for endpoint in sx.EXERCISE_REQUIREMENTS}
    sampling_strata = {endpoint: 0 for endpoint in sx.EXERCISE_REQUIREMENTS}
    invalid_eligibility: list[str] = []
    for row in admitted:
        if not isinstance(row, dict) or not isinstance(row.get("family"), str):
            raise sx.Refused("an admitted row has no family")
        by_family[row["family"]] = by_family.get(row["family"], 0) + 1
        eligibility = row.get("exercise_eligibility")
        expected = sx.exercise_eligibility(row.get("capability_exercise") or {})
        if eligibility != expected:
            invalid_eligibility.append(str(row.get("lineage_id")))
            continue
        for endpoint, block in eligibility.items():
            sampling_strata[endpoint] += int(block["eligible"] is True)
        # Power is an observed property of the executed pair, not of a
        # hash-derived pre-acquisition stratum. Read only the exercised bit here;
        # violation counts and verdicts remain outside frame verification.
        observations = row.get("endpoint_observations")
        if not isinstance(observations, dict):
            raise sx.Refused(f"{row.get('lineage_id')} has no endpoint observation map")
        for endpoint in power:
            observation = observations.get(endpoint)
            if not isinstance(observation, dict) or type(observation.get("exercised")) is not bool:
                raise sx.Refused(
                    f"{row.get('lineage_id')} has no actual exercise indicator for {endpoint}"
                )
            power[endpoint] += int(observation["exercised"] is True)
    candidates = int((acquired.get("frame") or {}).get("candidates", -1))
    considered = int(acquired.get("lineages_considered", -1))
    ending = "EXHAUSTED" if candidates >= 0 and considered == candidates else "NEITHER"
    family_floor_count = sum(count >= sx.MIN_PER_FAMILY for count in by_family.values())
    concerns = []
    if acquired.get("acquisition_state") != "ACQUIRED":
        concerns.append(
            "the worker only staged the roster; no exact observation batch was acquired"
        )
    if ending != "EXHAUSTED":
        concerns.append("the exact frozen roster was not exhausted")
    if len(admitted) < sx.MIN_TOTAL:
        concerns.append(f"total {len(admitted)} is below {sx.MIN_TOTAL}")
    if family_floor_count < sx.MIN_FAMILIES:
        concerns.append(
            f"only {family_floor_count} families have at least {sx.MIN_PER_FAMILY} rows; need {sx.MIN_FAMILIES}"
        )
    for endpoint, count in power.items():
        if count < sx.MIN_EXERCISING:
            concerns.append(
                f"{endpoint} has {count} pre-score exercising rows; need {sx.MIN_EXERCISING}"
            )
    if invalid_eligibility:
        concerns.append(
            "exercise eligibility differs from frozen capability flags: "
            + ", ".join(invalid_eligibility)
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
        "design_bindings": verified_bindings,
        "ending": ending,
        "counts": {
            "total": len(admitted),
            "by_family": dict(sorted(by_family.items())),
            "families_at_floor": family_floor_count,
        },
        "exercise_power": power,
        "predeclared_sampling_strata": sampling_strata,
        "exercise_definition": {
            "source": "actual endpoint_observations[*].exercised from the completed observation batch",
            "requirements": {key: list(value) for key, value in sx.EXERCISE_REQUIREMENTS.items()},
            "score_outcomes_inspected": False,
            "violation_counts_inspected": False,
            "predeclared_capability_flags_are_sampling_strata_only": True,
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
        raise sx.Refused("SFIR1 frame may only be sealed at receipts/sfir1-frame-authority.json")
    acquired = sx.read_json(acquisition)
    body = assess(acquired, acquisition)
    sx.exclusive_json(authority, body)
    return body


def verify(path: Path = sx.FRAME_AUTHORITY) -> dict:
    body = sx.verify_fixed_authority(path, sx.FRAME_AUTHORITY, SCHEMA)
    if body.get("state") != "SCORABLE":
        raise sx.Refused(f"SFIR1 frame authority is {body.get('state')}, not SCORABLE")
    # Revalidate the protocol's closed execution-source manifest at every use,
    # not only when the frame was first sealed.  Otherwise a scorer modified
    # after frame verification could consume a once-valid frame.
    verified = sx.reverify_recorded_bindings(body.get("design_bindings"))
    if verified != body.get("design_bindings"):
        raise sx.Refused("frame authority design bindings are not canonical")
    acquisition = sx.ROOT / body["acquisition"]
    if not acquisition.is_file() or sx.sha_file(acquisition) != body.get("acquisition_sha256"):
        raise sx.Refused("frame authority acquisition binding moved")
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
