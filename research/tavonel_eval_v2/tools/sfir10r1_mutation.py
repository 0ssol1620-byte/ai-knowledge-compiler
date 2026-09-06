#!/usr/bin/env python3
"""Prospective mutation audit for the complete SFIR10R1 instrument.

Run only after the instrument sources are committed and before the freeze.  Each
mutation weakens one safety property that matters to scientific interpretation.
The baseline must be green; a missing anchor or a surviving mutation is a failed
audit.  Every target is restored in ``finally`` and the engine refuses to start
if a target differs from its committed bytes.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
REPO = NS.parents[1]
OUTPUT = NS / "receipts/sfir10r1-mutation-baselines.json"
SCHEMA = "tavonel.sfir10r1.mutation_baselines.v1"

TESTS = (
    "tests/test_sfir10r1_protocol.py",
    "tests/test_sfir10r1_transport.py",
    "tests/test_sfir10r1_runner.py",
)


@dataclass(frozen=True, slots=True)
class Mutation:
    label: str
    target: str
    old: str
    new: str


MUTATIONS = (
    Mutation(
        "M01 choose partition two instead of mechanical successor",
        "tools/sfir10r1_protocol.py",
        "PARTITION_INDEX = (PREDECESSOR_PARTITION_INDEX + 1) % PARTITION_COUNT",
        "PARTITION_INDEX = (PREDECESSOR_PARTITION_INDEX + 2) % PARTITION_COUNT",
    ),
    Mutation(
        "M02 enable adaptive mid-segment polling",
        "tools/sfir10r1_protocol.py",
        "POLL_DURING_SEGMENT = False",
        "POLL_DURING_SEGMENT = True",
    ),
    Mutation(
        "M03 stop requiring reset evidence",
        "tools/sfir10r1_protocol.py",
        "REQUIRE_RATE_RESET_HEADER = True",
        "REQUIRE_RATE_RESET_HEADER = False",
    ),
    Mutation(
        "M04 reserve one charge instead of worst-case redirect cost",
        "tools/sfir10r1_protocol.py",
        "REQUEST_RESERVATION_CHARGES = MAX_HOPS_PER_LOGICAL_REQUEST",
        "REQUEST_RESERVATION_CHARGES = 1",
    ),
    Mutation(
        "M05 permit a segment request that can overspend",
        "tools/sfir10r1_transport.py",
        "self.provider_charged + reserve > protocol.USABLE_CHARGE_PER_WINDOW",
        "self.provider_charged > protocol.USABLE_CHARGE_PER_WINDOW",
    ),
    Mutation(
        "M06 permit a root request that can overspend",
        "tools/sfir10r1_transport.py",
        "self.root_charged + reserve > protocol.PER_ROOT_CHARGE_ALLOWANCE",
        "self.root_charged > protocol.PER_ROOT_CHARGE_ALLOWANCE",
    ),
    Mutation(
        "M07 ignore provider reset drift on a response",
        "tools/sfir10r1_transport.py",
        "if reset != self.window.reset_epoch:",
        "if False and reset != self.window.reset_epoch:",
    ),
    Mutation(
        "M08 accept multi-charge hop as attributable",
        "tools/sfir10r1_transport.py",
        "if delta < 0 or delta > 1:",
        "if False and (delta < 0 or delta > 1):",
    ),
    Mutation(
        "M09 turn rate-limit HTTP status into ordinary transport handling",
        "tools/sfir10r1_transport.py",
        "if status in protocol.RATE_LIMIT_HTTP_STATUSES:",
        "if False and status in protocol.RATE_LIMIT_HTTP_STATUSES:",
    ),
    Mutation(
        "M10 invent main when metadata has no default branch",
        "tools/sfir10r1_transport.py",
        '"default_branch": branch if isinstance(branch, str) and branch else None,',
        '"default_branch": branch if isinstance(branch, str) and branch else "main",',
    ),
    Mutation(
        "M11 report transport stop as frontier exhaustion",
        "tools/sfir10r1_runner.py",
        "except (transport_module.SegmentClose, transport_module.MeasurementUnproven):\n"
        "            store.frontier.release(entry)\n"
        "            raise\n"
        "        except transport_module.TransportStop:\n"
        "            store.frontier.release(entry)\n"
        "            return STOPPED",
        "except (transport_module.SegmentClose, transport_module.MeasurementUnproven):\n"
        "            store.frontier.release(entry)\n"
        "            raise\n"
        "        except transport_module.TransportStop:\n"
        "            store.frontier.release(entry)\n"
        "            return EXHAUSTED",
    ),
    Mutation(
        "M12 call unfinished roots exhausted when windows end",
        "tools/sfir10r1_runner.py",
        'state["root_states"][key] = STOPPED',
        'state["root_states"][key] = EXHAUSTED',
    ),
    Mutation(
        "M13 resume after crash without a sealed segment receipt",
        "tools/sfir10r1_runner.py",
        "if not segment_path.is_file():",
        "if False and not segment_path.is_file():",
    ),
    Mutation(
        "M14 permit a short roster to enter the census",
        "tools/sfir10r1_protocol.py",
        "REQUIRE_FULL_ROSTER = True",
        "REQUIRE_FULL_ROSTER = False",
    ),
    Mutation(
        "M15 restore V10 all-refused false completeness",
        "tools/sfir10r1_runner.py",
        "complete = stopped == 0 and counted > 0",
        "complete = stopped == 0",
    ),
    Mutation(
        "M16 ignore an existing immutable root snapshot and reseed",
        "tools/sfir10r1_runner.py",
        'if existing is not None:\n        if existing["repository_numeric_id"] != repository_id:',
        "if False and existing is not None:\n"
        '        if existing["repository_numeric_id"] != repository_id:',
    ),
    Mutation(
        "M17 allow counted root without immutable revision snapshot",
        "tools/sfir10r1_runner.py",
        "if status in {EXHAUSTED, STOPPED} and snapshot is None:",
        "if False and status in {EXHAUSTED, STOPPED} and snapshot is None:",
    ),
    Mutation(
        "M18 misclassify metadata transport failure as identity refusal",
        "tools/sfir10r1_transport.py",
        'response = self.get(f"https://api.github.com/repos/{address}")',
        "try:\n"
        '            response = self.get(f"https://api.github.com/repos/{address}")\n'
        "        except TransportStop as exc:\n"
        "            raise IdentityRefused(str(exc)) from exc",
    ),
)


class MutationRefused(RuntimeError):
    pass


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _pytest(*, first_fail: bool) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, "-m", "pytest", *TESTS, "-q", "--no-header"]
    if first_fail:
        args.append("-x")
    return subprocess.run(  # noqa: S603 - sys.executable and fixed local tests only
        args,
        cwd=NS,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _target_clean(relative: str) -> None:
    repo_relative = f"research/tavonel_eval_v2/{relative}"
    result = subprocess.run(  # noqa: S603 - fixed git argv plus declared target
        [  # noqa: S607 - repository follows the existing git-from-PATH convention
            "git",
            "status",
            "--porcelain",
            "--",
            repo_relative,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or result.stdout.strip():
        raise MutationRefused(
            f"target {repo_relative} is not clean against its commit; mutation audit refused"
        )


def audit() -> dict[str, Any]:
    if OUTPUT.exists():
        raise MutationRefused("SFIR10R1 mutation receipt already exists; it is immutable")
    for target in sorted({row.target for row in MUTATIONS}):
        _target_clean(target)

    baseline = _pytest(first_fail=False)
    if baseline.returncode != 0:
        raise MutationRefused(
            "baseline is red; mutations would be meaningless:\n"
            + baseline.stdout[-3000:]
            + baseline.stderr[-1000:]
        )

    outcomes = []
    for mutation in MUTATIONS:
        path = NS / mutation.target
        original = path.read_bytes()
        text = original.decode("utf-8")
        newline = "\r\n" if b"\r\n" in original else "\n"
        old = mutation.old.replace("\n", newline)
        new = mutation.new.replace("\n", newline)
        if text.count(old) != 1:
            outcomes.append(
                {
                    "label": mutation.label,
                    "target": mutation.target,
                    "outcome": "ANCHOR_NOT_UNIQUE",
                    "anchor_count": text.count(old),
                }
            )
            continue
        path.write_bytes(text.replace(old, new, 1).encode("utf-8"))
        try:
            try:
                result = _pytest(first_fail=True)
                outcome = "KILLED" if result.returncode != 0 else "SURVIVED"
            except subprocess.TimeoutExpired:
                outcome = "HUNG"
        finally:
            path.write_bytes(original)
        outcomes.append(
            {
                "label": mutation.label,
                "target": mutation.target,
                "outcome": outcome,
            }
        )

    bad = [row for row in outcomes if row["outcome"] != "KILLED"]
    body = {
        "schema": SCHEMA,
        "baseline": {
            "returncode": baseline.returncode,
            "summary_tail": [line for line in baseline.stdout.splitlines() if line.strip()][-3:],
        },
        "mutations_declared": len(MUTATIONS),
        "mutations_killed": len(MUTATIONS) - len(bad),
        "survivors_or_invalid": bad,
        "all_baselines_green": baseline.returncode == 0,
        "all_mutations_killed": not bad,
        "outcomes": outcomes,
        "what_this_establishes": (
            f"the selected synthetic controls detect these {len(MUTATIONS)} declared weakenings; "
            "it does not prove absence of other defects"
        ),
    }
    report = {**body, "mutation_digest": _digest(body)}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    return report


def main() -> int:
    try:
        report = audit()
    except MutationRefused as exc:
        print(f"REFUSED {exc}")
        return 1
    print(
        json.dumps(
            {
                "mutations_declared": report["mutations_declared"],
                "mutations_killed": report["mutations_killed"],
                "all_mutations_killed": report["all_mutations_killed"],
                "mutation_digest": report["mutation_digest"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["all_mutations_killed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
