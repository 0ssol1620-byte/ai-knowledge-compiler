#!/usr/bin/env python3
"""Freeze the complete SFIR10R4 executable instrument before opening partition four."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
REPO = NS.parents[1]
OUTPUT = NS / "receipts/sfir10r4-instrument-freeze.json"
R3_ROSTER = NS / "receipts/sfir10r3-cohort-roster.json"
R3_TERMINAL = NS / "receipts/sfir10r3-terminal-unproven.json"
R3_FREEZE = NS / "receipts/sfir10r3-instrument-freeze.json"
R3_INPUT_BINDING = NS / "receipts/sfir10r3-cohort-input-binding.json"
MUTATION_RECEIPT = NS / "receipts/sfir10r4-mutation-baselines-v2.json"

sys.path.insert(0, str(NS / "tools"))
import sfir10r4_protocol as protocol  # noqa: E402

SCHEMA = "tavonel.sfir10r4.instrument_freeze.v1"

COMPONENTS = (
    "research/tavonel_eval_v2/tools/sfir10r4_protocol.py",
    "research/tavonel_eval_v2/tools/sfir10r4_transport.py",
    "research/tavonel_eval_v2/tools/sfir10r4_runner.py",
    "research/tavonel_eval_v2/tools/sfir10r4_bind_input.py",
    "research/tavonel_eval_v2/tools/sfir10r4_mutation.py",
    "research/tavonel_eval_v2/tools/sfir10r4_freeze.py",
    "research/tavonel_eval_v2/tools/sfir8_frontier.py",
    "research/tavonel_eval_v2/tools/sfir9_selection.py",
    "research/tavonel_eval_v2/tools/sfir9_cohort_input.py",
    "research/tavonel_eval_v2/tools/sfir9_protocol.py",
    "research/tavonel_eval_v2/tools/sfir7_catalog_parser.py",
    "research/tavonel_eval_v2/tools/sfir7_projection.py",
    "research/tavonel_eval_v2/tools/sfir7_frame.py",
    "research/tavonel_eval_v2/tools/sfir7_roots.py",
    "research/tavonel_eval_v2/tools/sfir9_execution_authority_gap.py",
)

CONTROLS = (
    "research/tavonel_eval_v2/tests/test_sfir10r4_protocol.py",
    "research/tavonel_eval_v2/tests/test_sfir10r4_transport.py",
    "research/tavonel_eval_v2/tests/test_sfir10r4_runner.py",
)

FORBIDDEN_BEFORE_FREEZE = (
    "receipts/sfir10r4-cohort-input-binding.json",
    "receipts/sfir10r4-cohort-roster.json",
    "receipts/sfir10r4-capacity-census.json",
    "receipts/sfir10r4-capacity-score.json",
    "receipts/sfir10r4-capacity-acceptance.json",
    "receipts/sfir10r4-terminal-unproven.json",
    "runtime/sfir10r4",
    "receipts/sfir10r4-segments",
)


class FreezeRefused(RuntimeError):
    pass


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(  # noqa: S603 - argv is constructed internally
        ["git", *args],  # noqa: S607 - repository follows the existing git-from-PATH convention
        cwd=REPO,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise FreezeRefused(result.stderr.decode(errors="replace").strip())
    return result


def _git_text(*args: str) -> str:
    return _git(*args).stdout.decode(errors="replace").strip()


def _bind(relative_path: str) -> dict[str, Any]:
    path = REPO / relative_path
    if not path.is_file():
        raise FreezeRefused(f"missing component {relative_path}")
    working = path.read_bytes()
    committed = _git("show", f"HEAD:{relative_path}")
    if committed.returncode != 0:
        raise FreezeRefused(f"{relative_path} is not committed at HEAD")
    if committed.stdout != working:
        raise FreezeRefused(f"{relative_path} differs between HEAD and working bytes")
    blob = _git_text("rev-parse", f"HEAD:{relative_path}")
    return {
        "relative_path": relative_path,
        "sha256": "sha256:" + hashlib.sha256(working).hexdigest(),
        "git_blob_id": blob,
        "bytes": len(working),
    }


def _namespace_clean() -> None:
    status = _git_text("status", "--porcelain", "--", "research/tavonel_eval_v2")
    if status:
        raise FreezeRefused(
            "research/tavonel_eval_v2 is dirty; freeze requires exact committed bytes: "
            + status.splitlines()[0]
        )


def _cohort_still_shut() -> None:
    for relative in FORBIDDEN_BEFORE_FREEZE:
        if (NS / relative).exists():
            raise FreezeRefused(f"{relative} exists before the SFIR10R4 freeze")
    historical = (
        _git(
            "log",
            "--all",
            "--diff-filter=A",
            "--format=%H",
            "--",
            "research/tavonel_eval_v2/receipts/sfir10r4-cohort-roster.json",
        )
        .stdout.decode()
        .strip()
    )
    if historical:
        raise FreezeRefused("an SFIR10R4 cohort roster already existed in repository history")


def _predecessor() -> dict[str, Any]:
    required = (R3_ROSTER, R3_TERMINAL, R3_FREEZE, R3_INPUT_BINDING)
    if not all(path.is_file() for path in required):
        raise FreezeRefused("the sealed SFIR10R3 predecessor evidence is incomplete")

    roster_raw = R3_ROSTER.read_bytes()
    roster = json.loads(roster_raw.decode("utf-8"))
    roster_body = {key: value for key, value in roster.items() if key != "roster_seal"}
    if _digest(roster_body) != roster.get("roster_seal"):
        raise FreezeRefused("R3 roster seal does not recompute")
    partition = roster.get("partition", {}).get("index")
    if partition != 3:
        raise FreezeRefused("R3 predecessor is not spent partition three")
    if roster.get("entry_count") != protocol.derive_n():
        raise FreezeRefused("R3 predecessor does not bind the prospectively required full roster")
    if protocol.PREDECESSOR_PARTITION_INDEX != 3 or protocol.PARTITION_INDEX != 4:
        raise FreezeRefused("R4 successor partition is not the mechanical next partition")

    terminal_raw = R3_TERMINAL.read_bytes()
    terminal = json.loads(terminal_raw.decode("utf-8"))
    terminal_body = {key: value for key, value in terminal.items() if key != "terminal_digest"}
    if _digest(terminal_body) != terminal.get("terminal_digest"):
        raise FreezeRefused("R3 terminal-unproven digest does not recompute")
    if terminal.get("schema") != "tavonel.sfir10r3.terminal_unproven.v1":
        raise FreezeRefused("R3 predecessor is not the frozen terminal-unproven study")
    if terminal.get("roster_seal") != roster.get("roster_seal"):
        raise FreezeRefused("R3 terminal receipt belongs to a different roster")
    if terminal.get("windows_used") != 0:
        raise FreezeRefused("R3 predecessor sealed a scientific window; R4 assumptions are invalid")
    reason = str(terminal.get("reason") or "")
    if not reason.startswith("provider reset epoch changed mid-segment (") or " -> " not in reason:
        raise FreezeRefused("R3 terminal reason differs from the rollover defect R4 closes")
    if terminal.get("what_this_means") != "no PASS or FAIL may be sealed from this cohort":
        raise FreezeRefused("R3 terminal receipt does not preserve the no-score ruling")

    r3_freeze = json.loads(R3_FREEZE.read_text(encoding="utf-8"))
    r3_input = json.loads(R3_INPUT_BINDING.read_text(encoding="utf-8"))
    if terminal.get("freeze_digest") != r3_freeze.get("freeze_digest"):
        raise FreezeRefused("R3 terminal receipt is not linked to the R3 instrument freeze")
    if roster.get("input_binding_digest") != r3_input.get("successor_binding_digest"):
        raise FreezeRefused("R3 roster is not linked to the R3 external input binding")

    return {
        "r3_roster_relative_path": "receipts/sfir10r3-cohort-roster.json",
        "r3_roster_file_sha256": "sha256:" + hashlib.sha256(roster_raw).hexdigest(),
        "r3_roster_seal": roster["roster_seal"],
        "r3_partition_index": 3,
        "r3_entry_count": roster["entry_count"],
        "r3_terminal_relative_path": "receipts/sfir10r3-terminal-unproven.json",
        "r3_terminal_file_sha256": "sha256:" + hashlib.sha256(terminal_raw).hexdigest(),
        "r3_terminal_digest": terminal["terminal_digest"],
        "r3_terminal_reason": terminal["reason"],
        "r3_windows_used": 0,
        "r3_no_pass_or_fail": True,
        "r3_freeze_digest": r3_freeze["freeze_digest"],
        "r3_input_binding_digest": r3_input["successor_binding_digest"],
        "r4_partition_index": 4,
        "what_is_inherited": "criterion, envelope, salt, partition count, catalogue frame",
        "what_is_not_reused": (
            "R3 root identities, candidate yields, and partial traversal outcomes do not enter R4 "
            "selection; only sealed predecessor metadata establishes that partition three is spent"
        ),
    }


def _run_controls() -> dict[str, Any]:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *CONTROLS,
        "-q",
    ]
    result = subprocess.run(  # noqa: S603 - sys.executable and fixed pytest paths only
        cmd, cwd=REPO, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise FreezeRefused(
            "SFIR10 controls are red:\n" + result.stdout[-4000:] + result.stderr[-2000:]
        )
    tail = [line for line in result.stdout.splitlines() if line.strip()][-3:]
    return {"command": cmd[1:], "returncode": 0, "summary_tail": tail}


def _mutation_baseline() -> dict[str, Any]:
    if not MUTATION_RECEIPT.is_file():
        raise FreezeRefused(
            "SFIR10 mutation-baseline receipt is absent; freeze requires a green "
            "post-commit mutation audit"
        )
    report = json.loads(MUTATION_RECEIPT.read_text(encoding="utf-8"))
    body = {key: value for key, value in report.items() if key != "mutation_digest"}
    if _digest(body) != report.get("mutation_digest"):
        raise FreezeRefused("SFIR10 mutation receipt digest does not recompute")
    if not report.get("all_baselines_green") or not report.get("all_mutations_killed"):
        raise FreezeRefused(
            f"SFIR10 mutation audit is not clean: survivors={report.get('survivors_or_invalid')}"
        )
    return {
        "relative_path": "research/tavonel_eval_v2/receipts/sfir10r4-mutation-baselines-v2.json",
        "file_sha256": "sha256:" + hashlib.sha256(MUTATION_RECEIPT.read_bytes()).hexdigest(),
        "mutation_digest": report["mutation_digest"],
        "mutations_declared": report["mutations_declared"],
        "mutations_killed": report["mutations_killed"],
    }


def freeze() -> dict[str, Any]:
    if OUTPUT.exists():
        raise FreezeRefused("SFIR10 freeze already exists; it cannot be retaken")
    _namespace_clean()
    _cohort_still_shut()
    frozen = protocol.Protocol().freeze()
    terms = frozen.terms()
    if terms["rate_window_execution"]["poll_during_segment"] is not False:
        raise FreezeRefused("unexpected adaptive rate polling")
    if terms["rate_window_execution"]["segment_start_observations"] != 1:
        raise FreezeRefused("segment-start observation schedule is not singular and fixed")
    execution = terms["rate_window_execution"]
    preflight = execution["accounting_sanity_preflight"]
    if preflight["requests"] != 10 or preflight["minimum_delta_each_response"] != 1:
        raise FreezeRefused("accounting sanity preflight is not the frozen ten-request proof")
    if preflight["wait_seconds"] != 0 or preflight["cohort_contact_before_success"] is not False:
        raise FreezeRefused("accounting sanity preflight permits adaptive wait or cohort contact")
    if preflight["external_extra_permitted"] is not True:
        raise FreezeRefused("R4 preflight unexpectedly requires credential exclusivity")
    if execution["capacity_claim_depends_on_exact_provider_cost"] is not False:
        raise FreezeRefused("R4 incorrectly couples capacity to exact provider cost")
    if execution["provider_cost_claim_policy"] != "WITHHOLD_UNLESS_ZERO_UNATTRIBUTED_EXTRA":
        raise FreezeRefused("R4 provider-cost withholding policy drifted")
    if execution["unattributed_extra_policy"] != (
        "RECORD_AS_EXTERNAL_INTERFERENCE_NEVER_CREDIT_TO_YIELD"
    ):
        raise FreezeRefused("R4 interference policy drifted")
    if execution["mid_segment_window_reset_policy"] != (
        "CLOSE_SEGMENT_DISCARD_BOUNDARY_RESPONSE_REPLAY_NEXT_WINDOW"
    ):
        raise FreezeRefused("R4 rollover boundary policy drifted")
    if execution["rollover_boundary_response_policy"] != "NEVER_CONSUME_AS_SCIENTIFIC_DATA":
        raise FreezeRefused("R4 could consume rollover boundary data")
    if execution["rollover_provider_cost_policy"] != (
        "WITHHOLD_EXACT_COST_FOR_BOUNDARY_SEGMENT"
    ):
        raise FreezeRefused("R4 rollover cost policy drifted")
    if execution["secondary_limit_minimum_wait_seconds"] != 60:
        raise FreezeRefused("R4 secondary-limit minimum wait drifted")
    controls = _run_controls()
    body = {
        "schema": SCHEMA,
        "state": "INSTRUMENT_FROZEN",
        "study_id": protocol.PROTOCOL_ID,
        "instrument_commit": _git_text("rev-parse", "HEAD"),
        "protocol_digest": frozen.digest(),
        "protocol_terms": terms,
        "components": [_bind(path) for path in COMPONENTS],
        "controls": [_bind(path) for path in CONTROLS],
        "control_run": controls,
        "mutation_baseline": _mutation_baseline(),
        "predecessor": _predecessor(),
        "cohort_state_at_freeze": "NO_SFIR10_ROSTER_ARTIFACT_IN_WORKTREE_OR_HISTORY",
        "authorises": (
            "bind the external catalogue input, then generate exactly one SFIR10R4 roster under "
            "partition four; after that roster is sealed, execute only this frozen census runner"
        ),
        "why_this_is_not_an_r3_repair": (
            "R3 remains terminal MEASUREMENT_UNPROVEN with no PASS or FAIL. R4 uses the next "
            "untouched partition and prospectively treats a documented provider-window rollover "
            "as a segment boundary while discarding the boundary response before selection."
        ),
    }
    report = {**body, "freeze_digest": _digest(body)}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    return report


def verify(report: dict[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in report.items() if k != "freeze_digest"}
    problems = []
    if _digest(body) != report.get("freeze_digest"):
        problems.append("freeze digest does not recompute")
    if report.get("protocol_digest") != protocol.Protocol().freeze().digest():
        problems.append("protocol digest differs from live protocol")
    return {"verified": not problems, "problems": problems}


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="freeze complete SFIR10 instrument").parse_args(argv)
    try:
        report = freeze()
    except FreezeRefused as exc:
        print(f"REFUSED {exc}")
        return 1
    print(
        json.dumps(
            {
                "state": report["state"],
                "instrument_commit": report["instrument_commit"],
                "protocol_digest": report["protocol_digest"],
                "freeze_digest": report["freeze_digest"],
                "components": len(report["components"]),
                "controls": len(report["controls"]),
                "verify": verify(report),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
