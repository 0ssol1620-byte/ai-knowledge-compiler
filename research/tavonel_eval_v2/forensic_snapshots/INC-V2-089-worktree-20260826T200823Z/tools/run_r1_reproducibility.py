#!/usr/bin/env python3
"""R1 driver: run the fixture twice and gate the seven declared properties.

The two runs are separate processes. That matters: ``new_run_id`` mixes the
process id into its seed, so two runs inside one interpreter within the same
second could collide, and a check that quietly depended on the driver's own
timing would be testing the clock rather than the plumbing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, ROOT, canonical_sha, now, rel, sha_file  # noqa: E402
from evidence import (  # noqa: E402
    POINTERS,
    ReceiptExists,
    receipt_path,
    write_immutable,
)

PROTOCOL = NS / "protocols" / "R1_receipt_reproducibility.yaml"
FIXTURE = NS / "tools" / "reproducibility_fixture.py"
STEM = "r1-reproducibility-fixture"


def launch() -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(FIXTURE)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "fixture failed: " + completed.stderr.strip().splitlines()[-1]
            if completed.stderr.strip()
            else "fixture failed"
        )
    line = [row for row in completed.stdout.splitlines() if row.startswith("{")][-1]
    return json.loads(line)


def read(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def self_hash_recomputes(body: dict[str, Any]) -> bool:
    declared = body.get("receipt_sha256")
    bare = {key: value for key, value in body.items() if key != "receipt_sha256"}
    return bool(declared) and canonical_sha(bare) == declared


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    started = now()

    first = launch()
    first_path = ROOT / first["receipt"]
    first_digest_after_run_one = sha_file(first_path)

    second = launch()
    second_path = ROOT / second["receipt"]
    first_digest_after_run_two = sha_file(first_path)

    left = read(first["receipt"])
    right = read(second["receipt"])

    # --- G_R1_OVERWRITE_REFUSED: demonstrated, not asserted -----------------
    collision: dict[str, Any] = {}
    before_collision = sha_file(first_path)
    try:
        write_immutable(
            STEM,
            {"schema": "tavonel.v2.r1_collision_probe.v1", "should_not_land": True},
            tool=FIXTURE,
            protocol=PROTOCOL,
            run_id=first["run_id"],
            pointer=False,
        )
        collision = {"refused": False, "exception": None}
    except ReceiptExists as error:
        collision = {"refused": True, "exception": type(error).__name__, "detail": str(error)}
    collision["target"] = rel(receipt_path(STEM, first["run_id"]))
    collision["file_unchanged_after_attempt"] = sha_file(first_path) == before_collision

    # --- G_R1_POINTER_IS_NOT_EVIDENCE ---------------------------------------
    pointer_path = POINTERS / (STEM + ".json")
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    payload_keys = set(left.get("payload", {}))
    pointer_carries_payload = sorted(payload_keys & set(pointer))
    pointer_checks = {
        "path": rel(pointer_path),
        "declares_is_evidence_false": pointer.get("is_evidence") is False,
        "points_to_second_run": pointer.get("points_to") == second["receipt"],
        "recorded_digest_matches_file": pointer.get("points_to_file_sha256")
        == sha_file(second_path),
        "carries_no_payload_field": not pointer_carries_payload,
        "payload_fields_found_in_pointer": pointer_carries_payload,
        "has_no_semantic_result_digest": "semantic_result_digest" not in pointer,
    }

    gates = {
        "G_R1_BOTH_RECEIPTS_EXIST": {
            "passed": first_path.is_file()
            and second_path.is_file()
            and self_hash_recomputes(left)
            and self_hash_recomputes(right),
            "first": first["receipt"],
            "second": second["receipt"],
            "first_self_hash_recomputes": self_hash_recomputes(left),
            "second_self_hash_recomputes": self_hash_recomputes(right),
        },
        "G_R1_DISTINCT_PATHS": {
            "passed": first["receipt"] != second["receipt"] and first["run_id"] != second["run_id"],
            "first_run_id": first["run_id"],
            "second_run_id": second["run_id"],
        },
        "G_R1_SAME_SEMANTIC_RESULT": {
            "passed": left["semantic_result_digest"] == right["semantic_result_digest"],
            "value": left["semantic_result_digest"],
        },
        "G_R1_SAME_TOOL_AND_PROTOCOL_DIGEST": {
            "passed": left["provenance"]["tool_sha256"] == right["provenance"]["tool_sha256"]
            and left["provenance"]["protocol_sha256"] == right["provenance"]["protocol_sha256"],
            "tool_sha256": left["provenance"]["tool_sha256"],
            "protocol_sha256": left["provenance"]["protocol_sha256"],
        },
        "G_R1_FIRST_RECEIPT_UNMODIFIED": {
            "passed": first_digest_after_run_one == first_digest_after_run_two,
            "after_run_one": first_digest_after_run_one,
            "after_run_two": first_digest_after_run_two,
        },
        "G_R1_OVERWRITE_REFUSED": {
            "passed": bool(collision["refused"])
            and bool(collision["file_unchanged_after_attempt"]),
            **collision,
        },
        "G_R1_POINTER_IS_NOT_EVIDENCE": {
            "passed": all(
                value for key, value in pointer_checks.items() if isinstance(value, bool)
            ),
            **pointer_checks,
        },
    }

    body: dict[str, Any] = {
        "schema": "tavonel.v2.r1_reproducibility_check.v1",
        "protocol": "R1_receipt_reproducibility",
        "closes": "the two-run reproducibility check owed by INC-V2-005",
        "started_at": started,
        "ended_at": now(),
        "fixture": rel(FIXTURE),
        "fixture_sha256": sha_file(FIXTURE),
        "subject": rel(NS / "tools" / "evidence.py"),
        "subject_sha256": sha_file(NS / "tools" / "evidence.py"),
        "runs": [first, second],
        "receipts_are_byte_identical": sha_file(first_path) == sha_file(second_path),
        "receipts_are_byte_identical_is_not_expected": (
            "run id and timestamp differ by design. A scheme whose two runs "
            "produced identical bytes could not distinguish two runs, which is "
            "exactly the property INC-V2-005 needed and did not have."
        ),
        "does_not_reproduce": (
            "any P0/P2/P3/P4 result. This reproduces a fixture, and the "
            "withdrawn INC-V2-005 two-run claim stays withdrawn."
        ),
        "gates": gates,
        "verdict": "PASS" if all(gate["passed"] for gate in gates.values()) else "FAIL",
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }

    written = write_immutable(
        "r1-reproducibility-check", body, tool=Path(__file__).resolve(), protocol=PROTOCOL
    )
    print(
        json.dumps(
            {
                "verdict": body["verdict"],
                "gates": {name: gate["passed"] for name, gate in gates.items()},
                **written,
            },
            sort_keys=True,
        )
    )
    return 0 if body["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
