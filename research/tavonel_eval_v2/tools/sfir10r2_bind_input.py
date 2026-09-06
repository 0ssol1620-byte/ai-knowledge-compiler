#!/usr/bin/env python3
"""Bind SFIR10R2's external catalogue/readers/frame after freeze, before partition two."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
REPO = NS.parents[1]
OUTPUT = NS / "receipts/sfir10r2-cohort-input-binding.json"
FREEZE = NS / "receipts/sfir10r2-instrument-freeze.json"

sys.path.insert(0, str(NS / "tools"))
import sfir9_cohort_input as underlying  # noqa: E402
import sfir10r2_freeze  # noqa: E402
import sfir10r2_protocol as protocol  # noqa: E402


class BindingRefused(RuntimeError):
    pass


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _added_at(relative_path: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed git argv plus repository-relative path
        [  # noqa: S607 - repository follows the existing git-from-PATH convention
            "git",
            "log",
            "--diff-filter=A",
            "--format=%aI",
            "--",
            relative_path,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    values = result.stdout.split()
    if result.returncode != 0 or not values:
        raise BindingRefused(f"cannot establish when {relative_path} entered the repository")
    return values[-1]


def bind() -> dict[str, Any]:
    if OUTPUT.exists():
        raise BindingRefused("SFIR10R2 input binding already exists; it is immutable")
    if (NS / "receipts/sfir10r2-cohort-roster.json").exists():
        raise BindingRefused(
            "SFIR10R2 roster already exists; input cannot be bound after cohort opening"
        )
    if not FREEZE.is_file():
        raise BindingRefused("SFIR10R2 instrument is not frozen")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    verification = sfir10r2_freeze.verify(freeze)
    if not verification["verified"]:
        raise BindingRefused(f"freeze does not verify: {verification['problems']}")

    base = underlying.binding(namespace=NS, repository_root=REPO)
    frame_added = base["inherited_frame"]["independence"]["frame_entered_repository_at"]
    successor_added = _added_at("research/tavonel_eval_v2/tools/sfir10r2_protocol.py")
    if not frame_added < successor_added:
        raise BindingRefused(
            f"eligibility frame entered at {frame_added}, not before SFIR10 protocol "
            f"{successor_added}"
        )

    body = {
        "schema": "tavonel.sfir10r2.cohort_input_binding.v1",
        "study_id": protocol.PROTOCOL_ID,
        "freeze_digest": freeze["freeze_digest"],
        "protocol_digest": protocol.Protocol().freeze().digest(),
        "underlying_binding_digest": base["binding_digest"],
        "underlying_binding": base,
        "successor_independence": {
            "eligibility_frame_entered_repository_at": frame_added,
            "sfir10r2_protocol_entered_repository_at": successor_added,
            "why": (
                "the eligibility predicates predate the successor protocol; they cannot have been "
                "written after seeing SFIR10R2's criterion or partition-two cohort"
            ),
        },
        "catalogue_is_external_not_a_predecessor_result": True,
        "this_binding_authorises_nothing": (
            "roster generation requires this binding and the separate SFIR10R2 instrument freeze"
        ),
    }
    report = {**body, "successor_binding_digest": _digest(body)}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    return report


def main() -> int:
    try:
        report = bind()
    except BindingRefused as exc:
        print(f"REFUSED {exc}")
        return 1
    print(
        json.dumps(
            {
                "study_id": report["study_id"],
                "successor_binding_digest": report["successor_binding_digest"],
                "underlying_binding_digest": report["underlying_binding_digest"],
                "catalogue_sha256": report["underlying_binding"]["member_verification"][
                    "sha256_recomputed"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
